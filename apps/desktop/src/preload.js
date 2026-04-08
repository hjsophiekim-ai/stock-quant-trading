const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("appBridge", {
  authLoad: () => ipcRenderer.invoke("auth:load"),
  authSave: (data) => ipcRenderer.invoke("auth:save", data),
  authClear: () => ipcRenderer.invoke("auth:clear"),
  onboardingMarkDone: () => ipcRenderer.invoke("onboarding:done"),
  onboardingStatus: () => ipcRenderer.invoke("onboarding:status"),
});
