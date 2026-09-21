const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktopApi', {
  login: (key) => ipcRenderer.invoke('auth:login', key),
  loginAccount: (username, password) => ipcRenderer.invoke('auth:loginAccount', username, password),
  logout: () => ipcRenderer.invoke('auth:logout'),
  getAuth: () => ipcRenderer.invoke('auth:get'),
  request: (pathname, method, body) => ipcRenderer.invoke('api:request', pathname, method, body),
  startVision: () => ipcRenderer.invoke('vision:start'),
  stopVision: () => ipcRenderer.invoke('vision:stop'),
  getVisionLogs: () => ipcRenderer.invoke('vision:logs'),
  startWechatBridge: () => ipcRenderer.invoke('wechat-bridge:start'),
  stopWechatBridge: () => ipcRenderer.invoke('wechat-bridge:stop'),
  getWechatBridgeStatus: () => ipcRenderer.invoke('wechat-bridge:status'),
  getWechatBridgeInstanceId: () => ipcRenderer.invoke('wechat-bridge:instance-id'),
  openExternal: (url) => ipcRenderer.invoke('shell:open', url),
});
