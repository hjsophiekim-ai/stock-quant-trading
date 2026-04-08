const path = require("path");
const fs = require("fs");
const { app, BrowserWindow, ipcMain } = require("electron");

const authPath = () => path.join(app.getPath("userData"), "auth_tokens.json");
const onboardingPath = () => path.join(app.getPath("userData"), "onboarding_done.json");

function readJsonSafe(p) {
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch {
    return null;
  }
}

/** 패키징된 앱의 src/runtime-config.js 에서 JSON 객체 추출 (메인 프로세스). */
function loadRuntimeConfigMain() {
  try {
    const p = path.join(__dirname, "runtime-config.js");
    const s = fs.readFileSync(p, "utf8");
    const start = s.indexOf("{");
    const end = s.lastIndexOf("}");
    if (start === -1 || end <= start) {
      return {};
    }
    return JSON.parse(s.slice(start, end + 1));
  } catch {
    return {};
  }
}

ipcMain.handle("auth:load", () => readJsonSafe(authPath()));
ipcMain.handle("auth:save", (_e, data) => {
  fs.mkdirSync(path.dirname(authPath()), { recursive: true });
  fs.writeFileSync(authPath(), JSON.stringify(data, null, 2), "utf8");
  return true;
});
ipcMain.handle("auth:clear", () => {
  try {
    fs.unlinkSync(authPath());
  } catch {
    /* ignore */
  }
  return true;
});
ipcMain.handle("onboarding:done", () => {
  fs.mkdirSync(path.dirname(onboardingPath()), { recursive: true });
  fs.writeFileSync(onboardingPath(), JSON.stringify({ done: true }), "utf8");
  return true;
});
ipcMain.handle("onboarding:status", () => {
  const j = readJsonSafe(onboardingPath());
  return Boolean(j && j.done);
});

function initialHtml() {
  const rc = loadRuntimeConfigMain();
  const isProduction = String(rc.APP_ENV || "").toLowerCase() === "production";
  // 설치형(production): 첫 실행부터 로그인 화면 — 백엔드는 원격(또는 사전 구성 URL)으로 두고 사용자가 수동으로 서버를 띄울 필요 없음.
  if (!isProduction) {
    const onboard = readJsonSafe(onboardingPath());
    if (!onboard || !onboard.done) {
      return "onboarding.html";
    }
  }
  const auth = readJsonSafe(authPath());
  if (auth && auth.accessToken) {
    return "dashboard.html";
  }
  return "login.html";
}

function createWindow() {
  const start = initialHtml();
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, start));
}

app.whenReady().then(createWindow);
