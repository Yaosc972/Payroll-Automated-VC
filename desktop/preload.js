const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("sigmaWorkbench", {
  platform: process.platform
});
