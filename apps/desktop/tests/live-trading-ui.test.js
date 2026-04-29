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
  assert.ok(html.includes("<th>순위</th>"));
});

test("live-trading.js uses live-exec auto-guarded endpoints", () => {
  const p = path.join(__dirname, "..", "src", "live-trading.js");
  const js = fs.readFileSync(p, "utf-8");
  assert.ok(js.includes("/api/live-exec/auto-guarded/start"));
  assert.ok(js.includes("/api/live-exec/auto-guarded/tick"));
  assert.ok(js.includes("/api/live-trading/settings"));
});

test("live-trading.html shows unlock flag controls on top", () => {
  const p = path.join(__dirname, "..", "src", "live-trading.html");
  const html = fs.readFileSync(p, "utf-8");
  assert.ok(html.includes("실주문 잠금 해제"));
  assert.ok(html.includes("id=\"liveFlagChk\""));
  assert.ok(html.includes("id=\"secondaryChk\""));
  assert.ok(html.includes("id=\"extraChk\""));
});

