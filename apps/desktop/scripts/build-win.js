const { execSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
const appEnv = process.env.APP_ENV || "production";

const runtimeConfigPath = path.join(__dirname, "..", "src", "runtime-config.js");
const runtimeConfigBody = `window.RUNTIME_CONFIG = ${JSON.stringify(
  { BACKEND_URL: backendUrl, APP_ENV: appEnv },
  null,
  2,
)};\n`;
fs.writeFileSync(runtimeConfigPath, runtimeConfigBody, "utf8");

try {
  execSync("npx electron-builder --win nsis", { stdio: "inherit" });
} catch (err) {
  process.exit(typeof err.status === "number" ? err.status : 1);
}
