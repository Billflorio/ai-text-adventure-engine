import { app, BrowserWindow, ipcMain } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import { spawn } from 'child_process';
import http from 'http';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let mainWindow;
let engineProcess = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
    autoHideMenuBar: true,
  });

  // Wait for the Python backend to boot up before loading
  const tryLoad = () => {
    http.get('http://127.0.0.1:8742/', (res) => {
      if (res.statusCode === 200) {
        mainWindow.loadURL('http://127.0.0.1:8742/');
      } else {
        setTimeout(tryLoad, 500);
      }
    }).on('error', () => {
      setTimeout(tryLoad, 500);
    });
  };

  mainWindow.loadFile(path.join(__dirname, 'loading.html'));
  tryLoad();
}

function startEngine() {
  if (engineProcess) return;

  const isDev = process.env.NODE_ENV === 'development';
  let enginePath;
  let args = [];

  if (isDev) {
    enginePath = 'python';
    args = [path.join(__dirname, '../../main.py')];
  } else {
    enginePath = path.join(process.resourcesPath, 'engine', 'engine.exe');
  }

  const dataDir = path.join(app.getPath('userData'), 'game_data');
  if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
  }

  console.log(`Starting engine from ${enginePath}`);
  engineProcess = spawn(enginePath, args, { 
    cwd: path.dirname(enginePath),
    env: { 
      ...process.env, 
      NO_BROWSER: '1',
      AITEXTGAME_DATA_DIR: dataDir
    } 
  });

  engineProcess.stdout.on('data', (data) => console.log(`engine: ${data}`));
  engineProcess.stderr.on('data', (data) => console.error(`engine err: ${data}`));
  
  engineProcess.on('close', (code) => {
    console.log(`engine exited with code ${code}`);
    engineProcess = null;
  });
}

app.whenReady().then(() => {
  startEngine();
  createWindow();

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('will-quit', () => {
  if (engineProcess) {
    engineProcess.kill();
  }
});

app.on('window-all-closed', function () {
  if (process.platform !== 'darwin') app.quit();
});


