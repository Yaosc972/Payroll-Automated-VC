const labels = {
  unactivated: "尚未激活",
  connecting: "正在连接",
  idle: "在线，等待任务",
  processing: "正在核对",
  offline: "连接已中断",
  proxy_unavailable: "系统代理不可用",
  network_offline: "网络连接不可用",
  service_unavailable: "核对服务暂不可用",
  recovering: "正在恢复连接",
  identity_expired: "身份已失效",
  failed: "任务需要重试",
  upgrade_required: "必须升级后使用",
  update_available: "有新版本可用"
};

const previewStatus = {
  status: "unactivated",
  message: "请从海外劳务报账页面激活本机核对助手。",
  workerVersion: "0.3.14"
};
const workerBridge = window.sigmaLaborWorker || {
  getStatus: async () => previewStatus,
  reconnect: async () => ({ restarted: false }),
  openUpdate: async () => ({ opened: false }),
  openLogs: async () => "",
  quit: async () => {},
  onStatus: () => () => {}
};

const elements = {
  statusTitle: document.querySelector("#statusTitle"),
  statusMessage: document.querySelector("#statusMessage"),
  runId: document.querySelector("#runId"),
  deviceId: document.querySelector("#deviceId"),
  workerVersion: document.querySelector("#workerVersion"),
  updatedAt: document.querySelector("#updatedAt"),
  updateStatus: document.querySelector("#updateStatus"),
  updateButton: document.querySelector("#updateButton"),
  reconnectButton: document.querySelector("#reconnectButton"),
  logsButton: document.querySelector("#logsButton"),
  quitButton: document.querySelector("#quitButton")
};

function renderStatus(status = {}) {
  const key = labels[status.status] ? status.status : "offline";
  document.body.dataset.status = key;
  elements.statusTitle.textContent = labels[key];
  elements.statusMessage.textContent = status.message || "状态暂不可用。";
  if (key === "update_available" && status.updateVersion) {
    elements.statusMessage.textContent = `版本 ${status.updateVersion} 已可用，请完成当前任务后更新。`;
  }
  elements.runId.textContent = status.runId || "-";
  elements.deviceId.textContent = status.localDeviceId || "未激活";
  elements.workerVersion.textContent = status.workerVersion || "-";
  elements.updatedAt.textContent = status.updatedAt ? new Date(status.updatedAt).toLocaleString("zh-CN", { hour12: false }) : "-";
  const updateRequired = key === "upgrade_required" || key === "update_available";
  elements.updateStatus.textContent = updateRequired
    ? `检测到需要更新${status.updateVersion ? `至 ${status.updateVersion}` : ""}，请下载并安装最新版。`
    : key === "unactivated"
      ? "激活助手后将自动检查更新"
      : "自动检查更新已开启";
  elements.updateButton.textContent = updateRequired ? "下载更新" : "打开更新页";
  elements.updateButton.disabled = key === "unactivated";
}

elements.reconnectButton.addEventListener("click", async () => {
  elements.reconnectButton.disabled = true;
  await workerBridge.reconnect();
  renderStatus(await workerBridge.getStatus());
  elements.reconnectButton.disabled = false;
});
elements.logsButton.addEventListener("click", () => workerBridge.openLogs());
elements.updateButton.addEventListener("click", () => workerBridge.openUpdate());
elements.quitButton.addEventListener("click", () => workerBridge.quit());

workerBridge.onStatus(renderStatus);
workerBridge.getStatus().then(renderStatus);
