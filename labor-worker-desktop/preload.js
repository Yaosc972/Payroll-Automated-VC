const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("sigmaLaborWorker", {
  getStatus: () => ipcRenderer.invoke("worker:get-status"),
  reconnect: () => ipcRenderer.invoke("worker:reconnect"),
  openUpdate: () => ipcRenderer.invoke("worker:open-update"),
  openLogs: () => ipcRenderer.invoke("worker:open-logs"),
  quit: () => ipcRenderer.invoke("worker:quit"),
  onStatus: (callback) => {
    const listener = (_event, status) => callback(status);
    ipcRenderer.on("worker:status", listener);
    return () => ipcRenderer.removeListener("worker:status", listener);
  }
});
