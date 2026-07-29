const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const ROOT = path.resolve(__dirname, "..");
const { exchangeActivation, parseActivationUrl } = require("../lib/activation");
const { createActivationDispatcher } = require("../lib/activation-dispatcher");
const { presentWorkerStatus } = require("../lib/status");
const { workerCommand } = require("../lib/worker-command");
const { activeWorkerPid } = require("../lib/worker-pid");

test("activation accepts only the worker scheme, HTTPS API, and one-time code", () => {
  const valid = parseActivationUrl(
    "sigma-overseas-labor-worker://activate?apiUrl=https%3A%2F%2Fsigma.example.com%2Fapi&code=sigma_labor_a1_12345678901234567890"
  );
  assert.deepEqual(valid, {
    apiUrl: "https://sigma.example.com",
    activationCode: "sigma_labor_a1_12345678901234567890"
  });
  assert.equal(parseActivationUrl("sigma-overseas-labor-worker://activate?apiUrl=http%3A%2F%2Flocalhost&code=sigma_labor_a1_12345678901234567890"), null);
  assert.equal(parseActivationUrl("sigma-overseas-labor-worker://other?apiUrl=https%3A%2F%2Fsigma.example.com&code=sigma_labor_a1_12345678901234567890"), null);
  assert.equal(parseActivationUrl("sigma-overseas-labor-worker://activate?apiUrl=https%3A%2F%2Fsigma.example.com&code=short"), null);
  assert.equal(parseActivationUrl("sigma-overseas-labor-worker://activate?apiUrl=https%3A%2F%2Fsigma.example.com&token=sigma_labor_w1_must-not-enter-url"), null);
  assert.equal(parseActivationUrl("sigma-workbench://worker-activate?apiUrl=https%3A%2F%2Fsigma.example.com&code=sigma_labor_a1_12345678901234567890"), null);
});

test("activation exchanges the one-time code over HTTPS before storing the worker token", async () => {
  const requests = [];
  const issued = await exchangeActivation(
    {
      apiUrl: "https://sigma.example.com",
      activationCode: "sigma_labor_a1_one-time-code"
    },
    {
      workerVersion: "0.3.2",
      fetchImpl: async (url, options) => {
        requests.push({ url: String(url), options });
        return {
          ok: true,
          json: async () => ({ token: "sigma_labor_w1_device-token", device: { id: "device-1" } })
        };
      }
    }
  );

  assert.equal(issued.token, "sigma_labor_w1_device-token");
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "https://sigma.example.com/api/labor/worker/activate");
  assert.equal(requests[0].options.method, "POST");
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    activationCode: "sigma_labor_a1_one-time-code",
    workerVersion: "0.3.2"
  });
  assert.equal(requests[0].options.body.includes("sigma_labor_w1_device-token"), false);
});

test("activation links received before app readiness are delivered once after readiness", async () => {
  const delivered = [];
  const dispatcher = createActivationDispatcher(async (value) => delivered.push(value));

  await dispatcher.enqueue("activation-before-ready");
  await dispatcher.enqueue("activation-before-ready");
  assert.deepEqual(delivered, []);

  await dispatcher.markReady();
  assert.deepEqual(delivered, ["activation-before-ready"]);

  await dispatcher.enqueue("activation-after-ready");
  assert.deepEqual(delivered, ["activation-before-ready", "activation-after-ready"]);
});

test("packaged worker command launches only the dedicated worker executable", () => {
  const command = workerCommand({
    packaged: true,
    resourcesRoot: "/Applications/worker/Contents/Resources",
    projectRoot: "/repo",
    platform: "darwin",
    python: "python3",
    settings: {
      apiUrl: "https://sigma.example.com",
      version: "0.3.0",
      dataRoot: "/Users/test/Library/Application Support/Sigma Labor Worker"
    }
  });
  assert.equal(command.command, "/Applications/worker/Contents/Resources/worker/sigma-labor-worker/sigma-labor-worker");
  assert.deepEqual(command.args, [
    "--api-url", "https://sigma.example.com",
    "--token-stdin",
    "--version", "0.3.0",
    "--data-root", "/Users/test/Library/Application Support/Sigma Labor Worker"
  ]);
  assert.equal(command.args.includes("opaque"), false);
  assert.equal(command.args.includes("--port"), false);
  assert.equal(command.command.includes("sigma-backend"), false);
});

test("packaged Windows worker launches the bundled exe without a Python dependency", () => {
  const command = workerCommand({
    packaged: true,
    resourcesRoot: "C:\\Program Files\\Sigma Labor Worker\\resources",
    projectRoot: "C:\\repo",
    platform: "win32",
    python: "python",
    settings: {
      apiUrl: "https://sigma.example.com",
      version: "0.3.9",
      dataRoot: "C:\\Users\\test\\AppData\\Roaming\\Sigma Labor Worker"
    }
  });
  assert.match(command.command, /sigma-labor-worker\.exe$/);
  assert.equal(command.command.includes("python"), false);
});

test("Windows installer uses a stable x64 artifact name", () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
  assert.equal(pkg.build.win.artifactName, "${productName}-${version}-windows-x64.${ext}");
  assert.deepEqual(pkg.build.win.target, [{ target: "nsis", arch: ["x64"] }]);
});

test("development worker command uses the Python module entrypoint", () => {
  const command = workerCommand({
    packaged: false,
    resourcesRoot: "/resources",
    projectRoot: "/repo",
    platform: "darwin",
    python: "python3",
    settings: { apiUrl: "https://sigma.example.com", version: "0.3.0", dataRoot: "/tmp/worker" }
  });
  assert.equal(command.command, "python3");
  assert.deepEqual(command.args.slice(0, 2), ["-m", "bonus_platform.worker.personal"]);
  assert.equal(command.cwd, "/repo");
});

test("packaged worker bundles and dispatches the local OCR runtime", () => {
  const entry = fs.readFileSync(path.join(ROOT, "worker_entry.py"), "utf8");
  const spec = fs.readFileSync(path.join(ROOT, "pyinstaller-worker.spec"), "utf8");
  const requirements = fs.readFileSync(path.join(ROOT, "requirements-worker.txt"), "utf8");

  assert.match(entry, /--ocr-task/);
  assert.match(entry, /tools\.labor_ocr_worker_task/);
  assert.match(spec, /collect_all\("rapidocr"\)/);
  assert.match(spec, /collect_all\("onnxruntime"\)/);
  assert.match(spec, /tools\.labor_ocr_worker_task/);
  assert.match(requirements, /rapidocr==3\.9\.1/);
  assert.match(requirements, /onnxruntime==1\.19\.2/);
});

test("package metadata is worker-only and uses the dedicated product identity", () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
  const serialized = JSON.stringify(packageJson);
  assert.equal(packageJson.name, "sigma-overseas-reconciliation-worker");
  assert.equal(packageJson.version, "0.3.13");
  assert.equal(packageJson.build.productName, "Σ海外报账核对助手");
  assert.match(fs.readFileSync(path.join(ROOT, "renderer", "app.js"), "utf8"), /workerVersion:\s*"0\.3\.13"/);
  assert.equal(packageJson.build.appId, "com.sigmaworkbench.overseaslaborworker");
  assert.deepEqual(packageJson.build.protocols[0].schemes, ["sigma-overseas-labor-worker"]);
  assert.match(packageJson.build.mac.icon, /overseas-labor-worker\.icns$/);
  assert.match(packageJson.build.win.icon, /overseas-labor-worker\.ico$/);
  assert.equal(serialized.includes("seed-data"), false);
  assert.equal(serialized.includes("bonus_platform/static"), false);
  assert.equal(serialized.includes("sigma-backend"), false);
  for (const filename of ["overseas-labor-worker.icns", "overseas-labor-worker.ico", "overseas-labor-worker.png"]) {
    assert.equal(fs.existsSync(path.join(ROOT, "assets", filename)), true, `${filename} must be packaged`);
  }
});

test("main process does not start the platform backend or load the local workbench", () => {
  const source = fs.readFileSync(path.join(ROOT, "main.js"), "utf8");
  assert.equal(source.includes("findFreePort"), false);
  assert.equal(source.includes("startBackend"), false);
  assert.equal(source.includes("127.0.0.1"), false);
  assert.equal(source.includes("bonus_platform/static"), false);
  assert.match(source, /stdio:\s*\["pipe",\s*"ignore",\s*"ignore"\]/);
  assert.match(source, /workerProcess\.stdin\.end\(/);
});

test("main process handles queued activation before renderer can request Keychain-backed status", () => {
  const source = fs.readFileSync(path.join(ROOT, "main.js"), "utf8");
  const readyBlock = source.slice(source.indexOf("app.whenReady()"));
  assert.ok(readyBlock.indexOf("await activationDispatcher.markReady()") < readyBlock.indexOf("createWindow()"));
});

test("main process exchanges activation through Electron networking for system proxy support", () => {
  const source = fs.readFileSync(path.join(ROOT, "main.js"), "utf8");
  assert.match(source, /fetchImpl:\s*\(input, init\)\s*=>\s*net\.fetch\(input, init\)/);
});

test("main process exchanges one-time activation before touching Keychain-backed storage", () => {
  const source = fs.readFileSync(path.join(ROOT, "main.js"), "utf8");
  const activationBlock = source.slice(source.indexOf("async function activateWorker"), source.indexOf("const activationDispatcher"));
  assert.ok(activationBlock.indexOf("exchangeActivation(") < activationBlock.indexOf("safeStorage.isEncryptionAvailable()"));
});

test("main process caches the decrypted activation instead of polling Keychain for status", () => {
  const source = fs.readFileSync(path.join(ROOT, "main.js"), "utf8");
  const loadBlock = source.slice(source.indexOf("function loadSettings"), source.indexOf("async function activateWorker"));
  const activationBlock = source.slice(source.indexOf("async function activateWorker"), source.indexOf("const activationDispatcher"));
  assert.match(source, /let cachedSettings;/);
  assert.match(loadBlock, /if \(cachedSettings !== undefined\) return cachedSettings;/);
  assert.match(activationBlock, /cachedSettings = \{ \.\.\.settings, token: issued\.token \};/);
});

test("renderer falls back to an unactivated state when the Electron bridge is unavailable", () => {
  const source = fs.readFileSync(path.join(ROOT, "renderer", "app.js"), "utf8");
  assert.match(source, /window\.sigmaLaborWorker \|\|/);
  assert.match(source, /status: "unactivated"/);
});

test("status presentation covers the worker lifecycle and strips unknown fields", () => {
  const cases = ["unactivated", "connecting", "idle", "processing", "offline", "failed", "upgrade_required"];
  for (const status of cases) {
    const presented = presentWorkerStatus(
      { status, message: "safe", token: "must-not-leak", runId: "labor-1", workerVersion: "0.3.0" },
      { activated: true, processRunning: true }
    );
    assert.equal(presented.status, status);
    assert.equal(presented.token, undefined);
  }
  assert.equal(presentWorkerStatus({}, { activated: false }).status, "unactivated");
});

test("pending update is shown only while the worker is not processing", () => {
  assert.equal(
    presentWorkerStatus({ status: "idle" }, { activated: true, processRunning: true, updateVersion: "0.4.0" }).status,
    "update_available"
  );
  assert.equal(
    presentWorkerStatus({ status: "processing" }, { activated: true, processRunning: true, updateVersion: "0.4.0" }).status,
    "processing"
  );
});

test("desktop shell exposes automatic update status and a safe browser download action", () => {
  const main = fs.readFileSync(path.join(ROOT, "main.js"), "utf8");
  const preload = fs.readFileSync(path.join(ROOT, "preload.js"), "utf8");
  const renderer = fs.readFileSync(path.join(ROOT, "renderer", "app.js"), "utf8");
  const html = fs.readFileSync(path.join(ROOT, "renderer", "index.html"), "utf8");

  assert.match(html, /id="updateStatus"/);
  assert.match(html, /自动检查更新已开启/);
  assert.match(html, /id="updateButton"/);
  assert.match(preload, /openUpdate:\s*\(\)\s*=>\s*ipcRenderer\.invoke\("worker:open-update"\)/);
  assert.match(main, /ipcMain\.handle\("worker:open-update"/);
  assert.match(main, /pendingUpdateDownloadUrl/);
  assert.match(main, /\/api\/labor\/worker\/release\/download/);
  assert.match(main, /shell\.openExternal\(downloadUrl/);
  assert.match(renderer, /workerBridge\.openUpdate\(\)/);
  assert.match(renderer, /key === "upgrade_required" \|\| key === "update_available"/);
});

test("active worker PID prevents duplicate desktop workers", () => {
  const root = fs.mkdtempSync(path.join(require("node:os").tmpdir(), "sigma-worker-pid-"));
  fs.writeFileSync(path.join(root, "worker.pid"), "4242");
  assert.equal(activeWorkerPid(root, (pid) => pid === 4242), 4242);
  assert.equal(activeWorkerPid(root, () => false), null);
  assert.equal(fs.existsSync(path.join(root, "worker.pid")), false);
  fs.rmSync(root, { recursive: true, force: true });
});
