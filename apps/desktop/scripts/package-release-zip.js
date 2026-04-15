/**
 * 기존 dist / releases 산출물을 정리한 뒤 Windows 빌드를 수행하고,
 * dist 전체 + 설치 안내 문서를 하나의 ZIP으로 묶습니다.
 *
 * 사용: apps/desktop 디렉터리에서
 *   npm run release:zip
 *
 * 환경변수(선택): BACKEND_URL, APP_ENV, ALLOW_LOCAL_BACKEND — 기본은 build:win:local 과 동일.
 */
const { execSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const desktopRoot = path.join(__dirname, "..");
const distDir = path.join(desktopRoot, "dist");
const releasesDir = path.join(desktopRoot, "releases");
const readmeSrc = path.join(desktopRoot, "RELEASE_INSTALL_KO.txt");
const pkg = JSON.parse(fs.readFileSync(path.join(desktopRoot, "package.json"), "utf8"));
const version = pkg.version || "0.1.0";

function rmrf(p) {
  fs.rmSync(p, { recursive: true, force: true });
}

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

function main() {
  ensureDir(releasesDir);

  for (const name of fs.readdirSync(releasesDir)) {
    if (name.endsWith(".zip")) {
      rmrf(path.join(releasesDir, name));
    }
  }

  if (fs.existsSync(distDir)) {
    console.log("[release:zip] removing previous dist/");
    rmrf(distDir);
  }

  if (!fs.existsSync(path.join(desktopRoot, "node_modules", "jimp"))) {
    console.error("[release:zip] devDependencies 가 없습니다. 먼저 이 폴더에서 `npm install` 을 실행하세요.");
    process.exit(1);
  }

  console.log("[release:zip] running build-win.js (production + local backend default) …");
  execSync("node scripts/build-win.js", {
    cwd: desktopRoot,
    stdio: "inherit",
    shell: true,
    env: {
      ...process.env,
      APP_ENV: process.env.APP_ENV || "production",
      ALLOW_LOCAL_BACKEND: process.env.ALLOW_LOCAL_BACKEND || "1",
      BACKEND_URL: process.env.BACKEND_URL || "http://127.0.0.1:8000",
    },
  });

  if (!fs.existsSync(distDir)) {
    console.error("[release:zip] dist/ not found after build.");
    process.exit(1);
  }

  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  const outName = `StockQuantDesktop-${version}-win64-bundle-${stamp}.zip`;
  const outZip = path.join(releasesDir, outName);
  const staging = path.join(releasesDir, "_staging_bundle");
  rmrf(staging);
  ensureDir(staging);

  const readmeDst = path.join(staging, "README_INSTALL_KO.txt");
  if (fs.existsSync(readmeSrc)) {
    fs.copyFileSync(readmeSrc, readmeDst);
  } else {
    fs.writeFileSync(readmeDst, "README missing — see repository apps/desktop/RELEASE_INSTALL_KO.txt\n", "utf8");
  }

  const distDst = path.join(staging, "dist");
  fs.cpSync(distDir, distDst, { recursive: true });

  console.log("[release:zip] creating " + outZip);
  /** Windows 10+ built-in bsdtar — ZIP 생성 (한글 경로에도 비교적 안전) */
  try {
    execSync(`tar.exe -a -c -f "${outZip}" -C "${staging}" .`, { stdio: "inherit", shell: true });
  } catch {
    const ps = `Compress-Archive -LiteralPath '${staging.replace(/'/g, "''")}' -DestinationPath '${outZip.replace(/'/g, "''")}' -Force`;
    execSync(`powershell -NoProfile -Command "${ps}"`, { stdio: "inherit", shell: true });
  }

  rmrf(staging);
  console.log("[release:zip] done:", outZip);
}

main();
