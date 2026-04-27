from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from backend.app.core.config import BackendSettings
from backend.app.risk.audit import append_risk_event
from backend.app.risk.live_unlock_gate import evaluate_paper_readiness, paper_readiness_data_health
from backend.app.services.broker_secret_service import BrokerSecretService
from backend.app.services.live_readiness_builder_store import LiveReadinessBuilderState, LiveReadinessBuilderStore

logger = logging.getLogger("backend.app.engine.live_readiness_builder")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(cfg: BackendSettings, event_type: str, payload: dict[str, Any]) -> None:
    append_risk_event(
        cfg.risk_events_jsonl,
        {
            "ts_utc": _utc_now_iso(),
            "event_type": event_type,
            **payload,
        },
    )


@dataclass
class ReadinessBuilderRuntime:
    user_id: str
    running: bool = False
    started_at_utc: str | None = None
    stopped_at_utc: str | None = None
    last_tick_at_utc: str | None = None
    consecutive_failures: int = 0
    last_error: str | None = None


@dataclass
class _LoopHandle:
    thread: threading.Thread
    stop_event: threading.Event
    runtime: ReadinessBuilderRuntime


_registry_lock = threading.Lock()
_registry: dict[str, _LoopHandle] = {}


def get_readiness_builder_loop_status(user_id: str) -> dict[str, Any]:
    uid = str(user_id or "")
    with _registry_lock:
        h = _registry.get(uid)
        if h is None:
            return {"running": False}
        return asdict(h.runtime)


def _maybe_start_paper_session(
    cfg: BackendSettings,
    broker_service: BrokerSecretService,
    user_id: str,
    *,
    market: str | None,
) -> tuple[bool, str]:
    if not bool(getattr(cfg, "readiness_builder_try_start_paper_session", True)):
        return False, "paper_session_autostart_disabled"
    try:
        from backend.app.engine.paper_session_controller import get_paper_session_controller
    except Exception:
        return False, "paper_session_controller_unavailable"

    ctrl = get_paper_session_controller()
    st = ctrl.status_payload(market=market, pref_user_id=user_id)
    if bool(st.get("user_session_active")):
        return True, "paper_session_already_running"
    sid = str(getattr(cfg, "readiness_builder_paper_strategy_id", "") or "").strip() or "swing_relaxed_v2"
    try:
        ctrl.start(user_id=user_id, strategy_id=sid, market=market)
        return True, "paper_session_started"
    except Exception as exc:
        return False, f"paper_session_start_failed: {exc}"


def _warmup_order_audit(cfg: BackendSettings) -> tuple[int, str]:
    try:
        from types import SimpleNamespace

        import pandas as pd

        from app.orders.order_manager import OrderManager
        from app.risk.rules import RiskRules, RiskSnapshot
        from backend.app.auth.kis_auth import issue_access_token
        from backend.app.clients.kis_client import build_kis_client_for_backend
        from backend.app.core.config import resolved_kis_api_base_url
        from backend.app.strategy.signal_engine import get_swing_signal_engine, parse_live_quote_from_kis
        from app.scheduler.kis_universe import build_kis_stock_universe
        from app.config import get_settings as get_app_settings
        from backend.app.core.config import get_backend_settings
    except Exception as exc:
        return 0, f"warmup_import_failed: {exc}"

    bcfg = get_backend_settings()
    acfg = get_app_settings()
    raw_uni = (bcfg.screener_universe_symbols or "").strip()
    symbols = [p.strip() for p in (raw_uni or acfg.paper_trading_symbols or "").split(",") if p.strip()]
    if not symbols:
        return 0, "empty_universe"

    base = resolved_kis_api_base_url(bcfg)
    tr = issue_access_token(app_key=bcfg.kis_app_key, app_secret=bcfg.kis_app_secret, base_url=base, timeout_sec=12)
    if not tr.ok or not tr.access_token:
        return 0, "kis_token_failed"
    client = build_kis_client_for_backend(bcfg, access_token=tr.access_token)
    lookback = max(int(bcfg.screener_lookback_days), 120)
    prices_df = build_kis_stock_universe(client, symbols, lookback_calendar_days=lookback)
    if prices_df.empty:
        return 0, "daily_universe_fetch_failed"
    quotes: dict[str, Any] = {}
    for sym in symbols[: min(30, len(symbols))]:
        try:
            raw = client.get_quote(sym)
            q = parse_live_quote_from_kis(sym, raw)
            if q:
                quotes[sym] = q
        except Exception:
            continue
    eng = get_swing_signal_engine()
    snap = eng.evaluate(prices_df, quotes, pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]))

    class _NoopBroker:
        def place_order(self, _order):
            return SimpleNamespace(order_id="", accepted=False, message="noop", status="noop", filled_quantity=0, avg_fill_price=0.0)

    om = OrderManager(broker=_NoopBroker(), risk_rules=RiskRules())
    rs = RiskSnapshot(daily_pnl_pct=0.0, total_pnl_pct=0.0, equity=1_000_000.0, market_filter_ok=True, position_values={}, market_regime=str(snap.market_regime or "sideways"))
    n = 0
    sigs = list(snap.signals or [])
    if sigs:
        for s in sigs[:5]:
            try:
                om.evaluate_signal(s.to_order_signal(), rs)
                n += 1
            except Exception:
                continue
        return n, "signals_evaluated"
    per = list(getattr(snap, "per_symbol", []) or [])
    if per:
        sym = str(getattr(per[0], "symbol", "") or "")
        if sym:
            from app.orders.models import OrderSignal

            om.evaluate_signal(
                OrderSignal(symbol=sym, side="buy", quantity=1, limit_price=None, stop_loss_pct=None, strategy_id="readiness_builder", signal_id=None),
                rs,
            )
            return 1, "fallback_symbol_evaluated"
    return 0, "no_symbols_evaluated"


def tick_readiness_builder_once(
    *,
    cfg: BackendSettings,
    broker_service: BrokerSecretService,
    user_id: str,
    market: str | None = None,
    store: LiveReadinessBuilderStore | None = None,
    warmup_func: Callable[[BackendSettings], tuple[int, str]] = _warmup_order_audit,
) -> dict[str, Any]:
    uid = str(user_id or "")
    s = store or LiveReadinessBuilderStore(getattr(cfg, "readiness_builder_state_store_json"))
    st = s.get(uid)
    st.enabled = True
    if st.started_at_utc is None:
        st.started_at_utc = _utc_now_iso()
    st.last_tick_at_utc = _utc_now_iso()
    st.updated_at_utc = _utc_now_iso()
    st.attempts = int(st.attempts or 0) + 1

    health0 = paper_readiness_data_health(cfg)
    target_pnl = int(getattr(cfg, "readiness_builder_target_pnl_rows", 10) or 10)
    target_audit = int(getattr(cfg, "readiness_builder_target_audit_rows", 3) or 3)
    ready0 = bool(health0.get("pnl_rows_found", 0) >= target_pnl) and bool(health0.get("audit_rows_found_tail", 0) >= target_audit)
    ready0 = bool(ready0) and bool(evaluate_paper_readiness(cfg).ok)
    if ready0:
        st.status = "ready"
        st.last_action = "already_ready"
        st.last_error = None
        st.last_health = dict(health0)
        s.upsert(st)
        return {"ok": True, "status": "ready", "state": asdict(st), "health": health0}

    paper_ok, paper_msg = _maybe_start_paper_session(cfg, broker_service, uid, market=market)
    st.last_action = paper_msg
    if paper_ok:
        _event(cfg, "READINESS_BUILDER_PAPER_SESSION", {"user_id": uid, "action": paper_msg})

    sync_ok = False
    sync_err: str | None = None
    try:
        from backend.app.portfolio.sync_engine import run_portfolio_sync

        run_portfolio_sync(backfill_days=int(cfg.portfolio_sync_backfill_days), settings=cfg)
        sync_ok = True
        st.last_action = "portfolio_sync_completed"
        _event(cfg, "READINESS_BUILDER_PORTFOLIO_SYNC", {"user_id": uid, "ok": True})
    except Exception as exc:
        sync_err = str(exc)
        st.last_action = "portfolio_sync_failed"
        _event(cfg, "READINESS_BUILDER_PORTFOLIO_SYNC", {"user_id": uid, "ok": False, "error": sync_err})

    audit_n, audit_msg = (0, "skipped")
    try:
        audit_n, audit_msg = warmup_func(cfg)
        st.last_action = f"order_audit_warmup:{audit_msg}"
        _event(cfg, "READINESS_BUILDER_ORDER_AUDIT", {"user_id": uid, "evaluated": int(audit_n), "message": audit_msg})
    except Exception as exc:
        st.last_action = "order_audit_warmup_failed"
        _event(cfg, "READINESS_BUILDER_ORDER_AUDIT", {"user_id": uid, "evaluated": 0, "error": str(exc)})

    health1 = paper_readiness_data_health(cfg)
    ready1 = bool(health1.get("pnl_rows_found", 0) >= target_pnl) and bool(health1.get("audit_rows_found_tail", 0) >= target_audit)
    ready1 = bool(ready1) and bool(evaluate_paper_readiness(cfg).ok)
    st.status = "ready" if ready1 else "building"
    st.last_error = None if (sync_ok and audit_n >= 0) else (sync_err or None)
    st.last_health = dict(health1)
    st.updated_at_utc = _utc_now_iso()
    s.upsert(st)
    return {
        "ok": True,
        "status": st.status,
        "state": asdict(st),
        "health": health1,
        "actions": {"paper_session": paper_msg, "portfolio_sync_ok": sync_ok, "order_audit_evaluated": int(audit_n), "order_audit_message": audit_msg},
    }


def start_readiness_builder(
    *,
    cfg: BackendSettings,
    broker_service: BrokerSecretService,
    user_id: str,
    market: str | None = None,
    store: LiveReadinessBuilderStore | None = None,
    tick_func: Callable[..., dict[str, Any]] = tick_readiness_builder_once,
) -> dict[str, Any]:
    uid = str(user_id or "")
    if not uid:
        return {"ok": False, "error": "empty_user_id"}
    if not bool(getattr(cfg, "readiness_builder_enabled", False)):
        return {"ok": True, "skipped": True, "reason": "READINESS_BUILDER_ENABLED is false"}
    s = store or LiveReadinessBuilderStore(getattr(cfg, "readiness_builder_state_store_json"))
    st = s.get(uid)
    st.enabled = True
    st.started_at_utc = st.started_at_utc or _utc_now_iso()
    st.stopped_at_utc = None
    st.status = st.status or "building"
    st.updated_at_utc = _utc_now_iso()
    s.upsert(st)

    interval = float(getattr(cfg, "readiness_builder_interval_sec", 60) or 60)
    max_attempts = int(getattr(cfg, "readiness_builder_max_attempts", 30) or 30)

    with _registry_lock:
        existing = _registry.get(uid)
        if existing is not None and existing.runtime.running:
            return {"ok": True, "already_running": True, "loop": asdict(existing.runtime), "state": asdict(st)}

        stop_event = threading.Event()
        runtime = ReadinessBuilderRuntime(user_id=uid, running=True, started_at_utc=_utc_now_iso())

        def _runner():
            while not stop_event.is_set():
                cur = s.get(uid)
                if not bool(cur.enabled):
                    runtime.running = False
                    runtime.stopped_at_utc = _utc_now_iso()
                    break
                if int(cur.attempts or 0) >= max_attempts:
                    cur.enabled = False
                    cur.status = "failed"
                    cur.last_action = "max_attempts_reached"
                    cur.last_error = "max_attempts_reached"
                    cur.stopped_at_utc = _utc_now_iso()
                    cur.updated_at_utc = _utc_now_iso()
                    s.upsert(cur)
                    runtime.running = False
                    runtime.stopped_at_utc = _utc_now_iso()
                    runtime.last_error = "max_attempts_reached"
                    _event(cfg, "READINESS_BUILDER_STOPPED", {"user_id": uid, "reason": "max_attempts_reached"})
                    break
                try:
                    runtime.last_tick_at_utc = _utc_now_iso()
                    out = tick_func(cfg=cfg, broker_service=broker_service, user_id=uid, market=market, store=s)
                    if out.get("status") == "ready":
                        cur2 = s.get(uid)
                        cur2.enabled = False
                        cur2.status = "ready"
                        cur2.last_action = "ready"
                        cur2.stopped_at_utc = _utc_now_iso()
                        cur2.updated_at_utc = _utc_now_iso()
                        s.upsert(cur2)
                        runtime.running = False
                        runtime.stopped_at_utc = _utc_now_iso()
                        _event(cfg, "READINESS_BUILDER_READY", {"user_id": uid})
                        break
                    runtime.consecutive_failures = 0
                    runtime.last_error = None
                except Exception as exc:
                    runtime.consecutive_failures += 1
                    runtime.last_error = str(exc)
                    _event(cfg, "READINESS_BUILDER_TICK_FAILED", {"user_id": uid, "error": runtime.last_error})
                stop_event.wait(interval)
            runtime.running = False

        th = threading.Thread(target=_runner, name=f"readiness-builder:{uid[:8]}", daemon=True)
        _registry[uid] = _LoopHandle(thread=th, stop_event=stop_event, runtime=runtime)
        _event(cfg, "READINESS_BUILDER_STARTED", {"user_id": uid, "interval_sec": interval, "max_attempts": max_attempts})
        th.start()
        return {"ok": True, "started": True, "loop": asdict(runtime), "state": asdict(st)}


def stop_readiness_builder(*, cfg: BackendSettings, user_id: str, reason: str = "stop_requested") -> dict[str, Any]:
    uid = str(user_id or "")
    s = LiveReadinessBuilderStore(getattr(cfg, "readiness_builder_state_store_json"))
    st = s.get(uid)
    st.enabled = False
    st.status = st.status or "stopped"
    st.stopped_at_utc = _utc_now_iso()
    st.updated_at_utc = _utc_now_iso()
    s.upsert(st)

    h = None
    with _registry_lock:
        h = _registry.get(uid)
        if h is not None:
            h.stop_event.set()
            h.runtime.running = False
            h.runtime.stopped_at_utc = _utc_now_iso()
    if h is not None:
        try:
            h.thread.join(timeout=2.0)
        except Exception:
            pass
    _event(cfg, "READINESS_BUILDER_STOPPED", {"user_id": uid, "reason": reason})
    return {"ok": True, "stopped": True, "state": asdict(st), "loop": get_readiness_builder_loop_status(uid)}

