# Electron Desktop App (Planning)

## Overview
This is a planning doc for an Electron wrapper around the existing FastAPI app so MetaList can run as a packaged desktop app.

## Current Web App Assumptions
- The backend is a FastAPI server (Python) serving SSR HTML + JSON APIs.
- The frontend is vanilla JS.
- Plain source-checkout `python main.py` now bootstraps every known namespace and exits; explicit single-namespace runs still support `--namespace`, positional namespace shorthand (`python main.py work`), `--port`, `--https-port`, `METALIST_PORT`, and optional TLS envs (`METALIST_HOST` is retired: each vault's Shared box decides where it listens).
  - For Electron, loopback remains the intended bind target.

## Electron Wrapper Approach
Wrap the existing server process with minimal app changes:

```
electron-app/
├── main.js              # Electron main process
├── preload.js           # Security bridge
├── package.json         # Electron deps
├── dist/                # Packaged Python backend
│   └── metalist/        # PyInstaller output (example)
└── build/               # Installers
```

## Technical Sketch

### Electron Main Process (main.js)
```javascript
const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');

let mainWindow;
let backendProcess;

function startBackend() {
  // Start packaged Python backend (example path)
  const backendPath = path.join(__dirname, 'dist', 'metalist', 'metalist');
  backendProcess = spawn(backendPath, [], {
    env: { ...process.env }
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js')
    }
  });

  // Wait for backend to be ready, then load
  setTimeout(() => {
    mainWindow.loadURL('http://127.0.0.1:8000');
  }, 2000);
}

app.whenReady().then(() => {
  startBackend();
  createWindow();
});

app.on('will-quit', () => {
  if (backendProcess) {
    backendProcess.kill();
  }
});
```

### Python Backend Packaging (PyInstaller)
MetaList’s runtime entrypoint is `main.py` (which starts Uvicorn for `app.main:app`). A packaging command will need to include templates/static assets.

Example (will likely need iteration per platform):
```bash
pyinstaller --onefile \
  --hidden-import=uvicorn \
  --hidden-import=fastapi \
  --add-data "app/templates:app/templates" \
  --add-data "app/static:app/static" \
  main.py
```

## Data Storage (Desktop)
- Current dev/prod default is `~/MetaList/namespaces/default/default.metalist.db`.
- Namespaced runs use `~/MetaList/namespaces/<namespace>/<namespace>.metalist.db` and a derived sibling file DB `~/MetaList/namespaces/<namespace>/<namespace>.metalist.files.db`.
- Remembered per-namespace launch ports are stored as plaintext metadata inside each namespace's main DB.
- Namespaced backups live under `~/MetaList/namespaces/<namespace>/backups/` and keep the namespace in the filename itself.
- A real desktop build should store the database under the OS app data directory (would require a code/config change).

## Product Notes
The Electron wrapper should expose the same feature set as the local web app. Any “free vs paid” split (cloud sync, backups, etc.) is a product decision and likely requires additional backend + client work beyond packaging.

## Next Steps
1. Validate FastAPI/Uvicorn packaging with PyInstaller.
2. Create minimal Electron proof-of-concept (start server, load `http://127.0.0.1:8000`).
   - Decide whether Electron should always launch a fixed namespace or expose namespace choice in the shell.
3. Decide on DB location strategy for desktop (app data dir vs user-chosen path).
4. Add lifecycle robustness: health-check the backend instead of a fixed `setTimeout`.
