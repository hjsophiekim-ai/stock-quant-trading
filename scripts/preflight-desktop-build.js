/**
 * 저장소 루트에서 실행: `apps/desktop/package.json` 존재 여부 확인.
 * 사용: node scripts/preflight-desktop-build.js
 * 루트 package.json 의 desktop:* 스크립트에서 자동 호출.
 */
const fs = require("node:fs");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "..");
const desktopPkg = path.join(repoRoot, "apps", "desktop", "package.json");

if (!fs.existsSync(desktopPkg)) {
  console.error("");
  console.error("[preflight] 실패: 다음 파일을 찾을 수 없습니다:");
  console.error(`  ${desktopPkg}`);
  console.error("");
  console.error("원인: 현재 작업 디렉터리가 저장소 루트가 아니거나, 로컬 복사본에서 apps/desktop 폴더가 빠졌습니다.");
  console.error("조치:");
  console.error("  1) PowerShell에서 저장소 루트로 이동했는지 확인 (git 저장소 최상위에 package.json 이 있는 폴더).");
  console.error("  2) git clone / 전체 폴더 복사로 apps/desktop 이 포함되었는지 확인.");
  console.error("  3) 확인 명령: Test-Path .\\apps\\desktop\\package.json   → True 여야 합니다.");
  console.error("");
  process.exit(1);
}

console.log(`[preflight] OK ${desktopPkg}`);
