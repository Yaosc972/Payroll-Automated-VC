const fs = require("node:fs");
const path = require("node:path");

function processIsAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (_error) {
    return false;
  }
}

function activeWorkerPid(dataRoot, isAlive = processIsAlive) {
  const pidPath = path.join(dataRoot, "worker.pid");
  try {
    const pid = Number.parseInt(fs.readFileSync(pidPath, "utf8").trim(), 10);
    if (Number.isInteger(pid) && pid > 0 && isAlive(pid)) return pid;
  } catch (_error) {
    return null;
  }
  try {
    fs.unlinkSync(pidPath);
  } catch (_error) {}
  return null;
}

module.exports = { activeWorkerPid };
