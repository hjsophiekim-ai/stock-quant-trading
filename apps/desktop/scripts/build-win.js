const { execSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const Jimp = require("jimp");
const toIco = require("to-ico");

const appEnv = process.env.APP_ENV || "production";
const rawBackendUrl = process.env.BACKEND_URL;
const allowLocalBackend =
  process.env.ALLOW_LOCAL_BACKEND === "1" || /^true$/i.test(process.env.ALLOW_LOCAL_BACKEND || "");

function resolveBackendUrl() {
  const trimmed = typeof rawBackendUrl === "string" ? rawBackendUrl.trim() : "";
  if (appEnv === "production") {
    if (!trimmed) {
      console.error(
        "[desktop-build] APP_ENV=production 빌드에는 BACKEND_URL 환경변수가 필수입니다. 예: BACKEND_URL=https://your-api.example.com",
      );
      process.exit(1);
    }
    if (/127\.0\.0\.1|localhost/i.test(trimmed) && !allowLocalBackend) {
      console.error(
        "[desktop-build] APP_ENV=production 빌드에서는 BACKEND_URL에 localhost/127.0.0.1 을 사용할 수 없습니다. 로컬 백엔드용 설치 파일만 만들 때는 ALLOW_LOCAL_BACKEND=1 을 함께 설정하세요.",
      );
      process.exit(1);
    }
    return trimmed;
  }
  return trimmed || "http://127.0.0.1:8000";
}

const backendUrl = resolveBackendUrl();
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

/** electron-builder 는 Windows 아이콘에 최소 256×256 이 필요합니다. */
async function ensureBuildIcon() {
  fs.mkdirSync(iconDir, { recursive: true });
  const image = await new Promise((resolve, reject) => {
    new Jimp(256, 256, 0x0f172aff, (err, img) => {
      if (err) reject(err);
      else resolve(img);
    });
  });
  const pngBuf = await image.getBufferAsync(Jimp.MIME_PNG);
  const icoBuf = await toIco([pngBuf], { sizes: [256, 128, 64, 48, 32, 16] });
  fs.writeFileSync(iconPath, icoBuf);
  console.log(`[desktop-build] wrote ${iconPath} (256px+ multi-size)`);
}

(async () => {
  await ensureBuildIcon();
  console.log(`[desktop-build] APP_ENV=${appEnv} BACKEND_URL=${backendUrl}`);

  try {
    if (fs.existsSync(runtimeConfigPath)) {
      hadPreviousFile = true;
      previousRuntimeConfig = fs.readFileSync(runtimeConfigPath, "utf8");
    }
    fs.writeFileSync(runtimeConfigPath, runtimeConfigBody, "utf8");
    process.env.CSC_IDENTITY_AUTO_DISCOVERY = "false";
    execSync("npx electron-builder --win nsis", { stdio: "inherit", env: process.env });
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
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
