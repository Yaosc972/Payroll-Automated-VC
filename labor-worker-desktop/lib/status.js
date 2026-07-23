const ALLOWED_STATUSES = new Set([
  "unactivated",
  "connecting",
  "idle",
  "processing",
  "offline",
  "failed",
  "upgrade_required"
]);

function presentWorkerStatus(raw = {}, options = {}) {
  const activated = Boolean(options.activated);
  const processRunning = Boolean(options.processRunning);
  if (!activated) {
    return {
      status: "unactivated",
      message: "请从海外劳务报账页面激活本机核对助手。",
      jobId: "",
      runId: "",
      updatedAt: "",
      workerVersion: String(options.workerVersion || ""),
      localDeviceId: ""
    };
  }

  let status = ALLOWED_STATUSES.has(raw.status) ? raw.status : (processRunning ? "connecting" : "offline");
  if (!processRunning && !["failed", "offline", "upgrade_required"].includes(status)) status = "offline";
  if (options.updateVersion && status === "idle") status = "update_available";
  const defaultMessage = status === "offline" ? "核对助手未运行，正在自动恢复。" : "正在连接核对服务。";
  return {
    status,
    message: String(raw.message || defaultMessage).slice(0, 240),
    jobId: String(raw.jobId || ""),
    runId: String(raw.runId || ""),
    updatedAt: String(raw.updatedAt || ""),
    workerVersion: String(raw.workerVersion || options.workerVersion || ""),
    localDeviceId: String(options.localDeviceId || ""),
    updateVersion: String(options.updateVersion || "")
  };
}

module.exports = { presentWorkerStatus };
