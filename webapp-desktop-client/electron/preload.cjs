const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  checkModels: () => ipcRenderer.invoke('check-models'),
  downloadModels: () => ipcRenderer.invoke('download-models'),
  startLocalServers: () => ipcRenderer.invoke('start-local-servers'),
  onDownloadProgress: (callback) => ipcRenderer.on('download-progress', (_event, value) => callback(value)),
});
