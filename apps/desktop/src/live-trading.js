const STRATEGIES = [
  { id: "final_betting_v1", tabLabel: "final_betting", title: "final_betting_v1", hint: "추천 시간: 장중(전략 시간대에 따라 후보가 없을 수 있음)" },
  { id: "scalp_rsi_flag_hf_v1", tabLabel: "RSI 고빈도", title: "scalp_rsi_flag_hf_v1", hint: "추천 시간: 장중(1m)" },
  { id: "scalp_macd_rsi_3m_v1", tabLabel: "MACD RSI 3m", title: "scalp_macd_rsi_3m_v1", hint: "추천 시간: 장중(3m)" },
  { id: "swing_relaxed_v2", tabLabel: "Swing", title: "swing_relaxed_v2", hint: "추천 시간: 일봉 기반(장 마감 이후/다음날 초반)" },
  { id: "multi", tabLabel: "Multi", title: "multi", hint: "위 전략을 모두 평가해 후보를 합산" },
];

function $(id) {
  return document.getElementById(id);
}

function fmtUtc(s) {
  if (!s) return "-";
  try {
    return new Date(s).toLocaleString();
  } catch {
    return String(s);
  }
}

function fmtNum(x, digits) {
  if (x == null || x === "") return "";
  const n = Number(x);
  if (!Number.isFinite(n)) return String(x);
  const d = typeof digits === "number" ? digits : 2;
  return n.toFixed(d);
}

function setBadge(el, ok, textOk, textBad) {
  el.textContent = ok ? textOk : textBad;
  el.className = "badge " + (ok ? "ok" : "bad");
}

function clearTbody(tbody) {
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
}

function td(txt) {
  const e = document.createElement("td");
  e.textContent = txt == null ? "" : String(txt);
  return e;
}

function renderShadowTable(rows, reasonText) {
  const tbody = $("shadowTbody");
  clearTbody(tbody);
  const empty = $("shadowEmpty");
  if (!rows || rows.length === 0) {
    empty.style.display = "block";
    empty.textContent = reasonText || "현재 조건을 만족한 후보가 없습니다.";
    return;
  }
  empty.style.display = "none";
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    const tr = document.createElement("tr");
    tr.appendChild(td(r.status || "candidate"));
    tr.appendChild(td(i + 1));
    tr.appendChild(td(r.symbol || ""));
    tr.appendChild(td(r.side || ""));
    tr.appendChild(td(r.quantity || ""));
    tr.appendChild(td(r.price == null ? "" : r.price));
    tr.appendChild(td(r.score == null ? "" : r.score));
    tr.appendChild(td(r.reason || ""));
    tr.appendChild(td(fmtUtc(r.ts_utc || r.asof_utc)));
    tbody.appendChild(tr);
  }
}

function renderAutoTable(rows) {
  const tbody = $("autoTbody");
  clearTbody(tbody);
  const empty = $("autoEmpty");
  if (!rows || rows.length === 0) {
    empty.style.display = "block";
    empty.textContent = "마지막 판단 결과가 없습니다.";
    return;
  }
  empty.style.display = "none";
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    const tr = document.createElement("tr");
    const px = r.price == null ? null : Number(r.price);
    const qty = Number(r.quantity || 0);
    const notional = px != null && Number.isFinite(px) ? px * qty : null;
    tr.appendChild(td(r.status || ""));
    tr.appendChild(td(i + 1));
    tr.appendChild(td(r.strategy_id || ""));
    tr.appendChild(td(r.symbol || ""));
    tr.appendChild(td(r.side || ""));
    tr.appendChild(td(qty || ""));
    tr.appendChild(td(notional == null ? "" : fmtNum(notional, 0)));
    tr.appendChild(td(r.score == null ? "" : r.score));
    tr.appendChild(td(r.reason || ""));
    tr.appendChild(td(r.order_id || ""));
    tr.appendChild(td(fmtUtc(r.ts_utc)));
    tbody.appendChild(tr);
  }
}

function renderAccountTables(account) {
  const posBody = $("posTbody");
  const ooBody = $("ooTbody");
  const fillBody = $("fillTbody");
  clearTbody(posBody);
  clearTbody(ooBody);
  clearTbody(fillBody);

  const positions = (account && account.positions) || [];
  const openOrders = (account && account.open_orders) || [];
  const fills = (account && account.recent_fills) || [];

  for (const p of positions) {
    const tr = document.createElement("tr");
    tr.appendChild(td(p.symbol || ""));
    tr.appendChild(td(p.quantity || ""));
    tr.appendChild(td(p.average_price == null ? "" : p.average_price));
    tr.appendChild(td(p.current_price == null ? "" : p.current_price));
    tr.appendChild(td(p.market_value == null ? "" : p.market_value));
    tr.appendChild(td(p.pnl_pct == null ? "" : p.pnl_pct));
    posBody.appendChild(tr);
  }

  for (const o of openOrders) {
    const tr = document.createElement("tr");
    tr.appendChild(td(o.order_id || ""));
    tr.appendChild(td(o.symbol || ""));
    tr.appendChild(td(o.side || ""));
    tr.appendChild(td(o.remaining_quantity || ""));
    tr.appendChild(td(o.price == null ? "" : o.price));
    tr.appendChild(td(fmtUtc(o.created_at_utc)));
    ooBody.appendChild(tr);
  }

  for (const f of fills) {
    const tr = document.createElement("tr");
    tr.appendChild(td(f.symbol || ""));
    tr.appendChild(td(f.side || ""));
    tr.appendChild(td(f.quantity || ""));
    tr.appendChild(td(f.price == null ? "" : f.price));
    tr.appendChild(td(f.order_id || ""));
    tr.appendChild(td(fmtUtc(f.filled_at_utc)));
    fillBody.appendChild(tr);
  }
}

let activeStrategyId = "final_betting_v1";
let lastCompact = null;
let lastShadow = null;
let lastTick = null;
let lastSellOnly = null;
let lastLiqPlans = null;

function setActiveTab(sid) {
  activeStrategyId = sid;
  for (const b of document.querySelectorAll(".tab")) {
    b.classList.toggle("active", b.dataset.strategyId === sid);
  }
  const meta = STRATEGIES.find((x) => x.id === sid) || STRATEGIES[0];
  $("strategyTitle").textContent = meta.title;
  $("strategyHint").textContent = meta.hint;
  const m = (lastCompact && lastCompact.auto && lastCompact.auto.mode) || "auto";
  $("modeSelect").value = String(m);
}

async function fetchJson(url, init) {
  const r = await authFetch(url, init || {});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((d && (d.detail?.error || d.detail || d.error)) || "request_failed");
  return d;
}

async function refreshCompact(includeRaw) {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  const url = base + "/api/live-trading/compact-dashboard" + (includeRaw ? "?include_raw=true" : "");
  const d = await fetchJson(url);
  lastCompact = d;
  $("rawCompact").textContent = JSON.stringify(d, null, 2);

  const blockers = (d.live && d.live.blockers) || [];
  $("statusLine").textContent = (d.live && d.live.warning_message) || "";
  $("bypassBadge").style.display = d.live && d.live.bypass ? "inline-block" : "none";

  $("liveOrderValue").textContent = d.live && d.live.can_place_live_order ? "가능" : "차단";
  $("autoEnabledValue").textContent = d.auto && d.auto.enabled ? "실행중" : "정지";
  $("selectedStrategyValue").textContent = (d.auto && d.auto.selected_strategy) || "-";
  $("marketModeValue").textContent = "-";
  $("lastTickValue").textContent = fmtUtc(d.auto && d.auto.last_tick_at_utc);
  $("dailyCountsValue").textContent = String((d.auto && d.auto.daily_buy_count) || 0) + " / " + String((d.auto && d.auto.daily_sell_count) || 0);
  $("blockersValue").textContent = blockers.length ? blockers[0] : "-";

  $("autoLoopBadge").textContent = d.auto && d.auto.enabled ? "자동 루프 ON" : "자동 루프 OFF";
  $("autoLoopBadge").className = "badge " + (d.auto && d.auto.enabled ? "ok" : "bad");

  const acc = d.account || {};
  if (acc.ok) {
    $("accountSummary").textContent =
      "positions=" + String((acc.positions || []).length) + " open_orders=" + String((acc.open_orders || []).length) + " fills=" + String((acc.recent_fills || []).length);
  } else {
    $("accountSummary").textContent = "계좌 조회 실패: " + String(acc.error || "");
  }

  renderAutoTable((d.auto && d.auto.last_eval_candidates) || []);
  renderAccountTables(acc);
}

async function fetchShadowForStrategy(strategyId) {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  if (strategyId === "final_betting_v1") {
    const out = await fetchJson(base + "/api/live-prep/final-betting/generate", { method: "POST" });
    lastShadow = out;
    $("rawShadow").textContent = JSON.stringify(out, null, 2);
    const rows = (out.items || []).map((c) => ({
      status: "candidate",
      symbol: c.symbol,
      side: c.side,
      quantity: c.quantity,
      price: c.price,
      score: c.score,
      reason: c.rationale || "",
      ts_utc: c.created_at_utc,
    }));
    const inspected = (out.shadow && out.shadow.fetch_summary && out.shadow.fetch_summary.length) || 0;
    const rejected = (out.shadow && out.shadow.rejection_reasons_by_symbol && Object.keys(out.shadow.rejection_reasons_by_symbol).length) || 0;
    const msg = rows.length
      ? ""
      : ("현재 조건을 만족한 후보가 없습니다. " + "(검사 " + String(inspected) + " / 탈락 " + String(rejected) + ")");
    renderShadowTable(rows, out.ok ? msg : (out.message || out.error || msg));
    return;
  }
  if (strategyId === "swing_relaxed_v2") {
    const out = await fetchJson(base + "/api/live-prep/swing-shadow/generate?strategy_id=" + encodeURIComponent(strategyId), { method: "POST" });
    lastShadow = out;
    $("rawShadow").textContent = JSON.stringify(out, null, 2);
    const rows = (out.generated_orders || []).map((o) => ({
      status: "candidate",
      symbol: o.symbol,
      side: o.side,
      quantity: o.quantity,
      price: o.price,
      score: null,
      reason: o.signal_reason,
      ts_utc: out.asof_utc,
    }));
    renderShadowTable(rows, out.ok ? "" : (out.message || out.error || ""));
    return;
  }
  if (strategyId === "multi") {
    const merged = [];
    for (const sid of ["final_betting_v1", "scalp_rsi_flag_hf_v1", "scalp_macd_rsi_3m_v1", "swing_relaxed_v2"]) {
      try {
        await fetchShadowForStrategy(sid);
        const raw = lastShadow;
        const rows =
          sid === "final_betting_v1"
            ? (raw.items || []).map((c) => ({
                status: "candidate",
                symbol: c.symbol,
                side: c.side,
                quantity: c.quantity,
                price: c.price,
                score: c.score,
                reason: c.rationale || "",
                ts_utc: c.created_at_utc,
              }))
            : (raw.generated_orders || []).map((o) => ({
                status: "candidate",
                symbol: o.symbol,
                side: o.side,
                quantity: o.quantity,
                price: o.price,
                score: null,
                reason: o.signal_reason,
                ts_utc: raw.asof_utc,
              }));
        for (const r of rows) merged.push({ ...r, reason: "[" + sid + "] " + (r.reason || "") });
      } catch (e) {
        merged.push({ status: "blocked", symbol: "", side: "", quantity: "", price: "", score: "", reason: "[" + sid + "] " + String(e.message || e) });
      }
    }
    $("rawShadow").textContent = JSON.stringify({ merged }, null, 2);
    renderShadowTable(merged, "");
    return;
  }
  const out = await fetchJson(base + "/api/live-prep/hf-shadow/generate?strategy_id=" + encodeURIComponent(strategyId), { method: "POST" });
  lastShadow = out;
  $("rawShadow").textContent = JSON.stringify(out, null, 2);
  const rows = (out.generated_orders || []).map((o) => ({
    status: "candidate",
    symbol: o.symbol,
    side: o.side,
    quantity: o.quantity,
    price: o.price,
    score: null,
    reason: o.signal_reason,
    ts_utc: out.asof_utc,
  }));
  renderShadowTable(rows, out.ok ? "" : (out.message || out.error || ""));
}

async function startAuto() {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  const mode = $("modeSelect").value || "auto";
  const out = await fetchJson(base + "/api/live-exec/auto-guarded/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy_id: activeStrategyId, mode, actor: "desktop-user", reason: "ui_start_auto_guarded" }),
  });
  lastTick = out;
  $("rawTick").textContent = JSON.stringify(out, null, 2);
  await refreshCompact(true);
}

async function stopAuto() {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  const out = await fetchJson(base + "/api/live-exec/auto-guarded/stop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor: "desktop-user", reason: "ui_stop_auto_guarded" }),
  });
  lastTick = out;
  $("rawTick").textContent = JSON.stringify(out, null, 2);
  await refreshCompact(true);
}

async function saveMode() {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  const mode = $("modeSelect").value || "auto";
  const out = await fetchJson(base + "/api/live-trading/auto-guarded/mode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy_id: activeStrategyId, mode, actor: "user", reason: "ui_save_mode" }),
  });
  lastTick = out;
  $("rawTick").textContent = JSON.stringify(out, null, 2);
  await refreshCompact(true);
}

async function tickOnce() {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  const mode = $("modeSelect").value || "auto";
  const out = await fetchJson(base + "/api/live-exec/auto-guarded/tick", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy_id: activeStrategyId, mode }),
  });
  lastTick = out;
  $("rawTick").textContent = JSON.stringify(out, null, 2);
  renderAutoTable(((out.state && out.state.last_eval_candidates) || out.last_eval_candidates || []));
  await refreshCompact(true);
}

async function toggleEmergencyStop() {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  const nowStop = lastCompact && lastCompact.live && lastCompact.live.emergency_stop;
  const out = await fetchJson(base + "/api/live-trading/emergency-stop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: !nowStop, actor: "user", reason: "ui_toggle_emergency_stop" }),
  });
  lastTick = out;
  $("rawTick").textContent = JSON.stringify(out, null, 2);
  await refreshCompact(true);
}

async function refreshDiagnostics() {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  try {
    const exec = await fetchJson(base + "/api/live-exec/status?include_history=false");
    $("rawLiveExec").textContent = JSON.stringify(exec, null, 2);
  } catch (e) {
    $("rawLiveExec").textContent = String(e.message || e);
  }
}

async function refreshSellOnly() {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  const out = await fetchJson(base + "/api/live-prep/sell-only-arm/status?execution_mode=live_shadow");
  lastSellOnly = out;
  $("rawSellOnly").textContent = JSON.stringify(out, null, 2);
}

async function toggleSellOnly() {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  if (!lastSellOnly) await refreshSellOnly();
  const enabled = !!(lastSellOnly && lastSellOnly.enabled);
  const out = await fetchJson(base + "/api/live-prep/sell-only-arm?execution_mode=live_shadow", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: !enabled, actor: "user", reason: "ui_toggle_sell_only" }),
  });
  lastSellOnly = out;
  $("rawSellOnly").textContent = JSON.stringify(out, null, 2);
}

async function refreshLiquidationPlans() {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  const out = await fetchJson(base + "/api/live-prep/batch-liquidation/plans?limit=5&execution_mode=live_shadow");
  lastLiqPlans = out;
  $("rawLiquidation").textContent = JSON.stringify(out, null, 2);
}

async function prepareLiquidation() {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  const out = await fetchJson(base + "/api/live-prep/batch-liquidation/prepare?execution_mode=live_shadow", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor: "user", reason: "ui_prepare_liquidation", use_market_order: true }),
  });
  $("rawLiquidation").textContent = JSON.stringify(out, null, 2);
  await refreshLiquidationPlans();
}

async function executeLatestLiquidation() {
  const base = effectiveBackendUrl().replace(/\/$/, "");
  if (!lastLiqPlans) await refreshLiquidationPlans();
  const items = (lastLiqPlans && lastLiqPlans.items) || [];
  if (!items.length) throw new Error("no_liquidation_plan");
  const planId = items[0].plan_id || items[0].planId || items[0].id;
  const out = await fetchJson(
    base + "/api/live-prep/batch-liquidation/" + encodeURIComponent(planId) + "/execute?execution_mode=live_shadow",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor: "user", reason: "ui_execute_liquidation" }),
    }
  );
  $("rawLiquidation").textContent = JSON.stringify(out, null, 2);
  await refreshLiquidationPlans();
}

function initTabs() {
  const tabs = $("strategyTabs");
  tabs.innerHTML = "";
  for (const s of STRATEGIES) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tab";
    b.dataset.strategyId = s.id;
    b.textContent = s.tabLabel;
    b.addEventListener("click", async () => {
      setActiveTab(s.id);
      renderShadowTable([], "현재 조건을 만족한 후보가 없습니다.");
      $("rawShadow").textContent = "";
    });
    tabs.appendChild(b);
  }
  setActiveTab(activeStrategyId);
}

function wireNav() {
  $("dashboardBtn").addEventListener("click", () => (window.location.href = "./dashboard.html"));
  $("domesticPaperBtn").addEventListener("click", () => (window.location.href = "./paper-trading.html"));
  $("usPaperBtn").addEventListener("click", () => (window.location.href = "./us-paper-trading.html"));
  $("domesticLiveBtn").addEventListener("click", () => (window.location.href = "./live-trading.html"));
  $("usLiveBtn").addEventListener("click", () => (window.location.href = "./us-live-trading.html"));
  $("performanceBtn").addEventListener("click", () => (window.location.href = "./performance.html"));
  $("brokerSettingsBtn").addEventListener("click", () => (window.location.href = "./broker-settings.html"));
  $("logoutBtn").addEventListener("click", async () => {
    await clearDesktopSession();
    window.location.href = "./login.html";
  });
}

(async function () {
  wireNav();
  initTabs();
  $("refreshBtn").addEventListener("click", async () => refreshCompact(true));
  $("shadowBtn").addEventListener("click", async () => fetchShadowForStrategy(activeStrategyId));
  $("startAutoBtn").addEventListener("click", startAuto);
  $("stopAutoBtn").addEventListener("click", stopAuto);
  $("tickBtn").addEventListener("click", tickOnce);
  $("saveModeBtn").addEventListener("click", saveMode);
  $("emergencyStopBtn").addEventListener("click", toggleEmergencyStop);
  $("diagRefreshBtn").addEventListener("click", async () => {
    await refreshCompact(true);
    await refreshDiagnostics();
    await refreshSellOnly();
    await refreshLiquidationPlans();
  });
  $("sellOnlyRefreshBtn").addEventListener("click", refreshSellOnly);
  $("sellOnlyToggleBtn").addEventListener("click", toggleSellOnly);
  $("liqRefreshBtn").addEventListener("click", refreshLiquidationPlans);
  $("liqPrepareBtn").addEventListener("click", prepareLiquidation);
  $("liqExecuteBtn").addEventListener("click", executeLatestLiquidation);

  await ensureValidBackendSession(effectiveBackendUrl());
  await refreshCompact(true);
  await refreshDiagnostics();
})();

