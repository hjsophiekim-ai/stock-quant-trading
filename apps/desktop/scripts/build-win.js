const { execSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const backendUrl = process.env.BACKEND_URL || "http://127.0.0.1:8000";
const appEnv = process.env.APP_ENV || "production";
const iconDir = path.join(__dirname, "..", "build", "icons");
const iconPath = path.join(iconDir, "icon.ico");

const runtimeConfigPath = path.join(__dirname, "..", "src", "runtime-config.js");
const runtimeConfigBody = `// Generated for electron-builder; workspace copy restored after pack.
window.RUNTIME_CONFIG = ${JSON.stringify(
  { BACKEND_URL: backendUrl, APP_ENV: appEnv },
  null,
  2,
)};
`;

let previousRuntimeConfig = null;
let hadPreviousFile = false;

function ensureBuildIcon() {
  fs.mkdirSync(iconDir, { recursive: true });
  if (fs.existsSync(iconPath)) {
    return;
  }
  const icoBase64 =
    "AAABAAEAEBAAAAAAIABoBAAAFgAAACgAAAAQAAAAIAAAAAEABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
  fs.writeFileSync(iconPath, Buffer.from(icoBase64, "base64"));
  console.warn(`[desktop-build] placeholder icon created: ${iconPath}`);
}

if (appEnv === "production" && /127\.0\.0\.1|localhost/i.test(backendUrl)) {
  console.warn(
    "[desktop-build] BACKEND_URL이 로컬입니다. 일반 사용자 배포는 운영 서버 URL(예: https://api.example.com)로 다시 빌드하세요.",
  );
}

ensureBuildIcon();
console.log(`[desktop-build] APP_ENV=${appEnv} BACKEND_URL=${backendUrl}`);

try {
  if (fs.existsSync(runtimeConfigPath)) {
    hadPreviousFile = true;
    previousRuntimeConfig = fs.readFileSync(runtimeConfigPath, "utf8");
  }
  fs.writeFileSync(runtimeConfigPath, runtimeConfigBody, "utf8");
  execSync("npx electron-builder --win nsis", { stdio: "inherit" });
} catch (err) {
  process.exit(typeof err.status === "number" ? err.status : 1);
} finally {
  if (hadPreviousFile && previousRuntimeConfig !== null) {
    fs.writeFileSync(runtimeConfigPath, previousRuntimeConfig, "utf8");
    console.log("[desktop-build] restored src/runtime-config.js");
  } else {
    fs.writeFileSync(
      runtimeConfigPath,
      `// 런타임 설정(비밀값 금지). 개발 시 기본값 — Windows 설치용 빌드는 npm run build:win* 가 임시로 덮어쓴 뒤 복원합니다.\nwindow.RUNTIME_CONFIG = {\n  "BACKEND_URL": "http://127.0.0.1:8000",\n  "APP_ENV": "development"\n};\n`,
      "utf8",
    );
    if (!hadPreviousFile) {
      console.warn("[desktop-build] wrote default development runtime-config.js (no backup existed)");
    }
  }
}
