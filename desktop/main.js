const { app, BrowserWindow, shell } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const net = require("net");
const path = require("path");

let backendProcess = null;
let mainWindow = null;

function projectRoot() {
  return path.resolve(__dirname, "..");
}

function resourcesRoot() {
  return process.resourcesPath || projectRoot();
}

function findFreePort(startPort = 8765) {
  return new Promise((resolve, reject) => {
    const tryPort = (port) => {
      const server = net.createServer();
      server.once("error", (error) => {
        if (error.code === "EADDRINUSE") {
          tryPort(port + 1);
          return;
        }
        reject(error);
      });
      server.once("listening", () => {
        server.close(() => resolve(port));
      });
      server.listen(port, "127.0.0.1");
    };
    tryPort(startPort);
  });
}

function waitForBackend(port, timeoutMs = 15000) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const poll = () => {
      const request = http.get(`http://127.0.0.1:${port}/api/health`, (response) => {
        response.resume();
        if (response.statusCode === 200) {
          resolve();
          return;
        }
        retry();
      });
      request.on("error", retry);
      request.setTimeout(1000, () => {
        request.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() - startedAt > timeoutMs) {
        reject(new Error("本地计算服务启动超时。"));
        return;
      }
      setTimeout(poll, 300);
    };
    poll();
  });
}

function pythonCommand() {
  return process.env.SIGMA_WORKBENCH_PYTHON || (process.platform === "win32" ? "python" : "python3");
}

function backendExecutablePath() {
  const executable = process.platform === "win32" ? "sigma-backend.exe" : "sigma-backend";
  return path.join(resourcesRoot(), "backend", "sigma-backend", executable);
}

function seedDataPath() {
  if (app.isPackaged) {
    return path.join(resourcesRoot(), "seed-data");
  }
  return path.join(projectRoot(), "outputs");
}

function backendCommand(port) {
  if (app.isPackaged) {
    return {
      command: backendExecutablePath(),
      args: ["--host", "127.0.0.1", "--port", String(port)],
      cwd: resourcesRoot()
    };
  }
  return {
    command: pythonCommand(),
    args: [path.join(projectRoot(), "desktop", "backend_entry.py"), "--host", "127.0.0.1", "--port", String(port)],
    cwd: projectRoot()
  };
}

async function startBackend(port) {
  const env = {
    ...process.env,
    SIGMA_WORKBENCH_HOME: app.getPath("userData"),
    SIGMA_WORKBENCH_SEED_DIR: seedDataPath(),
    PYTHONUNBUFFERED: "1"
  };
  const backend = backendCommand(port);
  backendProcess = spawn(backend.command, backend.args, {
    cwd: backend.cwd,
    env,
    stdio: "pipe",
    windowsHide: true
  });
  backendProcess.stdout.on("data", (chunk) => console.log(`[backend] ${chunk}`));
  backendProcess.stderr.on("data", (chunk) => console.error(`[backend] ${chunk}`));
  backendProcess.on("exit", (code) => {
    if (code !== 0 && mainWindow) {
      console.error(`Backend exited with code ${code}`);
    }
    backendProcess = null;
  });
  await waitForBackend(port);
}

function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1180,
    minHeight: 760,
    title: "西格玛工作台",
    backgroundColor: "#f4f7fb",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  mainWindow.loadURL(`http://127.0.0.1:${port}/`);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

function showStartupError(error) {
  mainWindow = new BrowserWindow({
    width: 720,
    height: 420,
    title: "西格玛工作台启动失败",
    backgroundColor: "#f8fafc"
  });
  const message = String(error && error.message ? error.message : error);
  mainWindow.loadURL(
    `data:text/html;charset=utf-8,${encodeURIComponent(`
      <html>
        <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:40px;background:#f8fafc;color:#0f172a;">
          <h1 style="font-size:24px;">西格玛工作台启动失败</h1>
          <p style="line-height:1.7;color:#475569;">本地计算服务未能正常启动。请确认应用目录完整，或联系维护人员查看日志。</p>
          <pre style="white-space:pre-wrap;background:#0f172a;color:white;border-radius:14px;padding:16px;">${message}</pre>
        </body>
      </html>
    `)}`
  );
}

async function boot() {
  const port = await findFreePort();
  try {
    await startBackend(port);
    createWindow(port);
  } catch (error) {
    showStartupError(error);
  }
}

app.whenReady().then(boot);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0 && !mainWindow) {
    boot();
  }
});
