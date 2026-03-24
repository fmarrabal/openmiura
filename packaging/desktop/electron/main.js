const { app, BrowserWindow } = require('electron');
function createWindow(){
  const win = new BrowserWindow({ width: 1440, height: 960, webPreferences: { contextIsolation: true } });
  win.loadURL(process.env.OPENMIURA_URL || 'http://127.0.0.1:8081/ui/');
}
app.whenReady().then(createWindow);
