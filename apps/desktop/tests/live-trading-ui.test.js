const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

test("live-trading.html hides raw diagnostics by default", () => {
  const p = path.join(__dirname, "..", "src", "live-trading.html");
  const html = fs.readFileSync(p, "utf-8");
  assert.ok(html.includes("<details>"));
  assert.ok(html.includes("상세보기 / 진단"));
  const idxDetails = html.indexOf("<details>");
  const idxRaw = html.indexOf("Raw compact-dashboard");
  assert.ok(idxRaw > idxDetails);
});

