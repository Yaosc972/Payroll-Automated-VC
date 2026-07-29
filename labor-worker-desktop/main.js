const { app, BrowserWindow, ipcMain, Menu, Notification, Tray, net, powerMonitor, safeStorage, session, shell } = require("electron");
const crypto = require("node:crypto");
const fs = require("node:fs");
const { spawn } = require("node:child_process");
const path = require("node:path");

const { exchangeActivation, parseActivationUrl } = require("./lib/activation");
const { createActivationDispatcher } = require("./lib/activation-dispatcher");
const { proxyEnvironment } = require("./lib/proxy");
const { presentWorkerStatus } = require("./lib/status");
const { workerCommand } = require("./lib/worker-command");
const { activeWorkerPid } = require("./lib/worker-pid");

let mainWindow = null;
let tray = null;
let workerProcess = null;
let statusTimer = null;
let updateTimer = null;
let supervisorTimer = null;
let quitting = false;
let workerStopping = false;
let supervisorBusy = false;
let pendingUpdateVersion = "";
let pendingUpdateDownloadUrl = "";
let workerProxyEnvironment = { SIGMA_WORKER_PROXY_MODE: "unresolved" };
let cachedSettings;

function projectRoot() {
  return path.resolve(__dirname, "..");
}

function resourcesRoot() {
  return process.resourcesPath || projectRoot();
}

function settingsPaths() {
  const root = app.getPath("userData");
  return {
    settings: path.join(root, "worker-settings.json"),
    credential: path.join(root, "worker-credential.bin"),
    status: path.join(root, "worker-status.json"),
    update: path.join(root, "worker-update.json"),
    logs: path.join(root, "logs")
  };
}

function loadSettings() {
  if (cachedSettings !== undefined) return cachedSettings;
  const paths = settingsPaths();
  if (!fs.existsSync(paths.settings) || !fs.existsSync(paths.credential) || !safeStorage.isEncryptionAvailable()) {
    cachedSettings = null;
    return cachedSettings;
  }
  try {
    const settings = JSON.parse(fs.readFileSync(paths.settings, "utf8"));
    const token = safeStorage.decryptString(fs.readFileSync(paths.credential));
    if (!settings.enabled || !settings.apiUrl || !token) {
      cachedSettings = null;
      return cachedSettings;
    }
    cachedSettings = { ...settings, token };
    return cachedSettings;
  } catch (error) {
    console.error("Unable to load worker activation", error);
    cachedSettings = null;
    return cachedSettings;
  }
}

async function activateWorker(value) {
  const activation = parseActivationUrl(value);
  if (!activation) return false;
  let issued;
  try {
    issued = await exchangeActivation(activation, {
      workerVersion: app.getVersion(),
      fetchImpl: (input, init) => net.fetch(input, init)
    });
  } catch (error) {
    console.error("Unable to exchange worker activation", error instanceof Error ? error.name : "Error");
    showWindow();
    return false;
  }
  if (!safeStorage.isEncryptionAvailable()) {
    console.error("Secure storage unavailable after worker activation exchange");
    showWindow();
    return false;
  }
  const paths = settingsPaths();
  const settings = {
    enabled: true,
    apiUrl: activation.apiUrl,
    localDeviceId: crypto.randomUUID(),
    activatedAt: new Date().toISOString()
  };
  fs.mkdirSync(path.dirname(paths.settings), { recursive: true });
  fs.writeFileSync(paths.settings, JSON.stringify(settings, null, 2), { mode: 0o600 });
  fs.writeFileSync(paths.credential, safeStorage.encryptString(issued.token), { mode: 0o600 });
  cachedSettings = { ...settings, token: issued.token };
  await refreshWorkerProxyEnvironment(settings.apiUrl);
  await restartWorker();
  showWindow();
  return true;
}

const activationDispatcher = createActivationDispatcher(activateWorker);

function currentStatus() {
  const paths = settingsPaths();
  const settings = loadSettings();
  if (!settings) {
    return presentWorkerStatus({}, { activated: false, workerVersion: app.getVersion() });
  }
  const localDeviceId = `${settings.localDeviceId.slice(0, 4)}…${settings.localDeviceId.slice(-4)}`;
  try {
    const status = JSON.parse(fs.readFileSync(paths.status, "utf8"));
    return presentWorkerStatus(status, {
      activated: true,
      processRunning: workerProcessRunning(),
      workerVersion: app.getVersion(),
      localDeviceId,
      updateVersion: pendingUpdateVersion
    });
  } catch (_error) {
    return presentWorkerStatus({}, {
      activated: true,
      processRunning: workerProcessRunning(),
      workerVersion: app.getVersion(),
      localDeviceId,
      updateVersion: pendingUpdateVersion
    });
  }
}

function sendStatus() {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send("worker:status", currentStatus());
}

function pythonCommand() {
  return process.env.SIGMA_WORKER_PYTHON || (process.platform === "win32" ? "python" : "python3");
}

function workerProcessRunning() {
  return Boolean(workerProcess) || Boolean(activeWorkerPid(app.getPath("userData")));
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitForWorkerExit(dataRoot, timeoutMilliseconds = 3000) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (activeWorkerPid(dataRoot) && Date.now() < deadline) {
    await delay(100);
  }
  return !activeWorkerPid(dataRoot);
}

async function refreshWorkerProxyEnvironment(apiUrl) {
  try {
    const rules = await session.defaultSession.resolveProxy(apiUrl);
    workerProxyEnvironment = proxyEnvironment(rules);
  } catch (error) {
    console.error("Unable to resolve the system proxy", error instanceof Error ? error.name : "Error");
    workerProxyEnvironment = { SIGMA_WORKER_PROXY_MODE: "unresolved" };
  }
  return workerProxyEnvironment;
}

function startWorker() {
  const settings = loadSettings();
  if (!settings || workerProcess) return false;
  const dataRoot = app.getPath("userData");
  if (activeWorkerPid(dataRoot)) return true;
  const token = settings.token;
  const command = workerCommand({
    packaged: app.isPackaged,
    resourcesRoot: resourcesRoot(),
    projectRoot: projectRoot(),
    platform: process.platform,
    python: pythonCommand(),
    settings: { apiUrl: settings.apiUrl, version: app.getVersion(), dataRoot }
  });
  const child = spawn(command.command, command.args, {
    cwd: command.cwd,
    env: {
      ...process.env,
      ...workerProxyEnvironment,
      SIGMA_WORKBENCH_HOME: app.getPath("userData"),
      PYTHONUNBUFFERED: "1"
    },
    stdio: ["pipe", "ignore", "ignore"],
    windowsHide: true
  });
  workerProcess = child;
  workerProcess.stdin.on("error", () => {});
  workerProcess.stdin.end(`${token}\n`);
  child.on("exit", () => {
    if (workerProcess === child) workerProcess = null;
    sendStatus();
    if (!quitting && !workerStopping) setTimeout(async () => {
      if (!activeWorkerPid(dataRoot)) {
        await refreshWorkerProxyEnvironment(settings.apiUrl);
        startWorker();
      }
    }, 1000);
  });
  sendStatus();
  return true;
}

async function stopWorker() {
  workerStopping = true;
  const dataRoot = app.getPath("userData");
  const actualPid = workerProcess?.pid || activeWorkerPid(dataRoot);
  if (actualPid) {
    try {
      process.kill(actualPid, "SIGTERM");
    } catch (_error) {}
  }
  const exited = await waitForWorkerExit(dataRoot);
  if (workerProcess?.pid === actualPid) workerProcess = null;
  workerStopping = false;
  sendStatus();
  return exited;
}

async function restartWorker() {
  const settings = loadSettings();
  await stopWorker();
  if (settings?.apiUrl) await refreshWorkerProxyEnvironment(settings.apiUrl);
  return startWorker();
}

async function superviseWorker({ refreshNetwork = false } = {}) {
  if (quitting || workerStopping || supervisorBusy) return false;
  const settings = loadSettings();
  if (!settings?.apiUrl) return false;
  supervisorBusy = true;
  try {
    if (!workerProcessRunning()) {
      await refreshWorkerProxyEnvironment(settings.apiUrl);
      return startWorker();
    }
    if (refreshNetwork && currentStatus().status !== "processing") {
      await restartWorker();
      return true;
    }
    return true;
  } finally {
    supervisorBusy = false;
  }
}

async function openUpdatePage() {
  const settings = loadSettings();
  if (!settings?.apiUrl) return { opened: false };
  const apiUrl = new URL(`${settings.apiUrl}/`);
  const candidate = pendingUpdateDownloadUrl || "/api/labor/worker/release/download";
  const resolved = new URL(candidate, apiUrl);
  if (
    resolved.origin !== apiUrl.origin
    || resolved.pathname !== "/api/labor/worker/release/download"
  ) {
    console.error("Refused an unexpected worker update URL");
    return { opened: false };
  }
  const downloadUrl = resolved.toString();
  await shell.openExternal(downloadUrl);
  return { opened: true };
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 520,
    height: 520,
    minWidth: 460,
    minHeight: 480,
    maxWidth: 680,
    title: "Σ海外报账核对助手",
    backgroundColor: "#eef3f7",
    icon: path.join(__dirname, "assets", "overseas-labor-worker.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  mainWindow.on("close", (event) => {
    if (!quitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function showWindow() {
  if (!mainWindow) createWindow();
  mainWindow.show();
  mainWindow.focus();
  sendStatus();
}

function createTray() {
  tray = new Tray(path.join(__dirname, "assets", "overseas-labor-worker.png"));
  tray.setToolTip("Σ海外报账核对助手");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "查看助手状态", click: showWindow },
    { label: "重新连接", click: () => void restartWorker() },
    { label: "检查 / 下载更新", click: () => void openUpdatePage() },
    { label: "打开日志目录", click: () => shell.openPath(settingsPaths().logs) },
    { type: "separator" },
    { label: "退出助手", click: () => app.quit() }
  ]));
  tray.on("double-click", showWindow);
}

function watchStatus() {
  statusTimer = setInterval(sendStatus, 2000);
  supervisorTimer = setInterval(() => void superviseWorker(), 5000);
  updateTimer = setInterval(() => {
    const updatePath = settingsPaths().update;
    if (!fs.existsSync(updatePath)) return;
    try {
      const manifest = JSON.parse(fs.readFileSync(updatePath, "utf8"));
      fs.unlinkSync(updatePath);
      const nextUpdateVersion = String(manifest.version || "");
      const shouldNotify = Boolean(nextUpdateVersion && nextUpdateVersion !== pendingUpdateVersion);
      pendingUpdateVersion = nextUpdateVersion;
      pendingUpdateDownloadUrl = String(manifest.downloadUrl || "/api/labor/worker/release/download");
      sendStatus();
      if (shouldNotify && Notification.isSupported()) {
        new Notification({ title: "核对助手有新版本", body: `版本 ${manifest.version || ""} 已可用，请完成当前任务后更新。` }).show();
      }
    } catch (error) {
      console.error("Unable to read worker update manifest", error);
    }
  }, 5000);
}

function registerIpc() {
  ipcMain.handle("worker:get-status", currentStatus);
  ipcMain.handle("worker:reconnect", async () => ({ restarted: await restartWorker() }));
  ipcMain.handle("worker:open-update", openUpdatePage);
  ipcMain.handle("worker:open-logs", async () => {
    fs.mkdirSync(settingsPaths().logs, { recursive: true });
    return shell.openPath(settingsPaths().logs);
  });
  ipcMain.handle("worker:quit", () => app.quit());
}

const singleInstanceLock = app.requestSingleInstanceLock();
if (!singleInstanceLock) app.quit();

app.on("open-url", (event, value) => {
  event.preventDefault();
  void activationDispatcher.enqueue(value);
});

app.on("second-instance", (_event, argv) => {
  const activationUrl = argv.find((value) => value.startsWith("sigma-overseas-labor-worker://activate"));
  if (activationUrl) void activationDispatcher.enqueue(activationUrl);
  showWindow();
});

app.whenReady().then(async () => {
  app.setAsDefaultProtocolClient("sigma-overseas-labor-worker");
  registerIpc();
  powerMonitor.on("resume", () => void superviseWorker({ refreshNetwork: true }));
  await activationDispatcher.markReady();
  const activationUrl = process.argv.find((value) => value.startsWith("sigma-overseas-labor-worker://activate"));
  if (activationUrl) await activationDispatcher.enqueue(activationUrl);
  if (!mainWindow) createWindow();
  createTray();
  watchStatus();
  const settings = loadSettings();
  if (settings?.apiUrl) await refreshWorkerProxyEnvironment(settings.apiUrl);
  startWorker();
});

app.on("window-all-closed", () => {});

app.on("activate", showWindow);

app.on("before-quit", () => {
  quitting = true;
  if (statusTimer) clearInterval(statusTimer);
  if (updateTimer) clearInterval(updateTimer);
  if (supervisorTimer) clearInterval(supervisorTimer);
  void stopWorker();
});
