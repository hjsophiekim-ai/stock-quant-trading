const { execSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
const appEnv = process.env.APP_ENV || "production";
const iconDir = path.join(__dirname, "..", "build", "icons");
const iconPath = path.join(iconDir, "icon.ico");

const runtimeConfigPath = path.join(__dirname, "..", "src", "runtime-config.js");
const runtimeConfigBody = `window.RUNTIME_CONFIG = ${JSON.stringify(
  { BACKEND_URL: backendUrl, APP_ENV: appEnv },
  null,
  2,
)};\n`;
fs.writeFileSync(runtimeConfigPath, runtimeConfigBody, "utf8");
ensureBuildIcon();
console.log(`[desktop-build] APP_ENV=${appEnv} BACKEND_URL=${backendUrl}`);

try {
  execSync("npx electron-builder --win nsis", { stdio: "inherit" });
} catch (err) {
  process.exit(typeof err.status === "number" ? err.status : 1);
}

function ensureBuildIcon() {
  fs.mkdirSync(iconDir, { recursive: true });
  if (fs.existsSync(iconPath)) {
    return;
  }
  // Minimal placeholder .ico so first build works on clean clone.
  const icoBase64 =
    "AAABAAEAEBAAAAAAIABoBAAAFgAAACgAAAAQAAAAIAAAAAEABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
  fs.writeFileSync(iconPath, Buffer.from(icoBase64, "base64"));
  console.warn(`[desktop-build] placeholder icon created: ${iconPath}`);
}
