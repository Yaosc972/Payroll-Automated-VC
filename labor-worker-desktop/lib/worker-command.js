const path = require("node:path");

function workerCommand({ packaged, resourcesRoot, projectRoot, platform, python, settings }) {
  const executable = platform === "win32" ? "sigma-labor-worker.exe" : "sigma-labor-worker";
  const targetPath = platform === "win32" ? path.win32 : path.posix;
  const args = [
    "--api-url", settings.apiUrl,
    "--token-stdin",
    "--version", settings.version,
    "--data-root", settings.dataRoot
  ];
  if (packaged) {
    return {
      command: targetPath.join(resourcesRoot, "worker", "sigma-labor-worker", executable),
      args,
      cwd: resourcesRoot
    };
  }
  return {
    command: python,
    args: ["-m", "bonus_platform.worker.personal", ...args],
    cwd: projectRoot
  };
}

module.exports = { workerCommand };
