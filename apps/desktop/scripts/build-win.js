const { execSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const projectRoot = path.resolve(__dirname, "..");

const desktopPkg = path.join(projectRoot, "package.json");
if (!fs.existsSync(desktopPkg)) {
  console.error(
    `[desktop-build] FATAL: package.json 을 찾을 수 없습니다: ${desktopPkg}`,
  );
  console.error(
    "[desktop-build] scripts/build-win.js 는 apps/desktop 폴더 안에서만 실행되어야 합니다. (npm run build:win 은 apps/desktop 에서 실행하거나, 저장소 루트에서 npm run desktop:build:win)",
  );
  process.exit(1);
}
console.log(`[desktop-build] projectRoot=${projectRoot}`);

require(path.join(__dirname, "verify-package-json.js"));

const backendUrl = process.env.BACKEND_URL || "http://127.0.0.1:8000";
const appEnv = process.env.APP_ENV || "production";

const runtimeConfigPath = path.join(projectRoot, "src", "runtime-config.js");
const runtimeConfigBody = `// Generated for electron-builder; workspace copy restored after pack.
window.RUNTIME_CONFIG = ${JSON.stringify(
  { BACKEND_URL: backendUrl, APP_ENV: appEnv },
  null,
  2,
)};
`;

let previousRuntimeConfig = null;
let hadPreviousFile = false;

if (appEnv === "production" && /127\.0\.0\.1|localhost/i.test(backendUrl)) {
  console.warn(
    "[desktop-build] BACKEND_URL이 로컬입니다. 일반 사용자 배포는 운영 서버 URL(예: https://api.example.com)로 다시 빌드하세요.",
  );
}

console.log(`[desktop-build] APP_ENV=${appEnv} BACKEND_URL=${backendUrl}`);

// 로컬/CI에서 코드 서명 인증서가 없을 때 불필요한 서명 탐색·실패를 줄입니다.
process.env.CSC_IDENTITY_AUTO_DISCOVERY ??= "false";

try {
  if (fs.existsSync(runtimeConfigPath)) {
    hadPreviousFile = true;
    previousRuntimeConfig = fs.readFileSync(runtimeConfigPath, "utf8");
  }
  fs.writeFileSync(runtimeConfigPath, runtimeConfigBody, "utf8");
  execSync("npx electron-builder --win nsis", {
    stdio: "inherit",
    cwd: projectRoot,
    env: process.env,
  });
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
