/**
 * electron-builder 는 package.json 의 dependencies 에
 * electron / electron-builder / electron-prebuilt / electron-rebuild 가 있으면 즉시 실패합니다.
 * (app-builder-lib checkDependencies)
 */
const fs = require("node:fs");
const path = require("node:path");

const pkgPath = path.join(__dirname, "..", "package.json");
const raw = fs.readFileSync(pkgPath, "utf8");
const pkg = JSON.parse(raw);

const forbidden = ["electron", "electron-builder", "electron-prebuilt", "electron-rebuild"];
const deps = pkg.dependencies && typeof pkg.dependencies === "object" ? pkg.dependencies : {};
for (const name of forbidden) {
  if (Object.prototype.hasOwnProperty.call(deps, name)) {
    console.error(
      `[desktop-build] INVALID: "${name}" must NOT be in "dependencies". Move it to "devDependencies". (${pkgPath})`,
    );
    process.exit(1);
  }
}

console.log(`[desktop-build] package.json OK (electron tooling not in dependencies): ${pkgPath}`);
