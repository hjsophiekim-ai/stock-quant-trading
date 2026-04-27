from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.orders.models import OrderRequest
from app.scheduler.equity_tracker import EquityTracker
from app.strategy.intraday_common import kst_now, parse_krx_hhmm

from backend.app.clients.kis_client import build_kis_client_for_live_user
from backend.app.risk.audit import append_risk_event
from backend.app.risk.live_exit_rules import evaluate_exit_for_position, set_cooldown_after_loss, should_skip_due_to_cooldown
from backend.app.services.broker_secret_service import BrokerSecretService
from backend.app.services.live_auto_guarded_store import LiveAutoGuardedState, LiveAutoGuardedStore
from backend.app.services.live_market_mode_store import LiveMarketModeStore
from backend.app.strategy.live_candidate_scoring import score_candidate
from backend.app.strategy.live_performance_scoring import get_performance_signal

logger = logging.getLogger("backend.app.engine.live_auto_guarded_engine")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_live_base_url(base_url: str) -> bool:
    b = (base_url or "").strip().lower()
    if not b:
        return False
    if "openapivts" in b:
        return False
    return True


def _market_open_ok(require_open: bool) -> tuple[bool, str]:
    if not require_open:
        return True, ""
    now = kst_now()
    t = now.time()
    t0 = parse_krx_hhmm("090000")
    t1 = parse_krx_hhmm("152000")
    if not (t0 <= t <= t1):
        return False, f"market_closed now_kst={now.isoformat()}"
    return True, ""


def _reset_daily_counts_if_needed(state: LiveAutoGuardedState) -> None:
    now = kst_now()
    day = now.strftime("%Y%m%d")
    if state.daily_kst_date != day:
        state.daily_kst_date = day
        state.daily_buy_count = 0
        state.daily_sell_count = 0
        state.recent_submits = {}


def _dup_key(side: str, symbol: str) -> str:
    return f"{str(side).strip().lower()}:{str(symbol).strip()}"


def _recent_dup_blocked(state: LiveAutoGuardedState, *, side: str, symbol: str, block_minutes: int) -> tuple[bool, str]:
    mins = max(0, int(block_minutes or 0))
    if mins <= 0:
        return False, ""
    k = _dup_key(side, symbol)
    ts = state.recent_submits.get(k)
    if not ts:
        return False, ""
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        return False, ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - dt
    if age.total_seconds() < float(mins) * 60.0:
        return True, f"duplicate_recent_submit key={k} age_sec={int(age.total_seconds())}"
    return False, ""


def _safe_price_from_quote(q: dict[str, Any]) -> float:
    v = q.get("stck_prpr") or q.get("last") or q.get("price") or q.get("current_price")
    try:
        return float(v)
    except Exception:
        return 0.0


def _build_live_broker(
    *,
    cfg: Any,
    client: Any,
    account_no: str,
    product_code: str,
    read_only: bool,
):
    from app.brokers.live_broker import LiveBroker

    return LiveBroker(
        kis_client=client,
        account_no=account_no,
        account_product_code=product_code,
        read_only=bool(read_only),
        live_trading_enabled=bool(getattr(cfg, "live_trading", False) or getattr(cfg, "live_trading_enabled", False)),
        live_trading_confirm=bool(getattr(cfg, "live_trading_confirm", False)),
        live_trading_extra_confirm=bool(getattr(cfg, "live_trading_extra_confirm", False)),
        trading_mode=str(getattr(cfg, "trading_mode", "")).strip().lower() or "paper",
        dry_run_log_enabled=bool(getattr(cfg, "live_order_dry_run_log", True)),
        logger=logger,
    )


def _equity_tracker_path(cfg: Any, user_id: str) -> Path:
    base = Path(getattr(cfg, "live_auto_guarded_equity_tracker_dir", "backend_data/live_auto_guarded"))
    return (base / f"equity_tracker_{user_id[:12]}.json").resolve()


def tick_live_auto_guarded(
    *,
    cfg: Any,
    broker_service: BrokerSecretService,
    user_id: str,
    safety: dict[str, Any],
) -> dict[str, Any]:
    store = LiveAutoGuardedStore(getattr(cfg, "live_auto_guarded_state_store_json"))
    st = store.get(user_id)
    _reset_daily_counts_if_needed(st)
    st.last_tick_at_utc = _utc_now_iso()
    st.updated_at_utc = _utc_now_iso()
    orders_allowed = bool(safety.get("ok"))
    blocked_before_order = not orders_allowed
    safety_blockers = list(safety.get("blockers") or [])

    def _event(event_type: str, payload: dict[str, Any]) -> None:
        append_risk_event(
            getattr(cfg, "risk_events_jsonl"),
            {
                "ts_utc": _utc_now_iso(),
                "event_type": event_type,
                "user_id": user_id,
                **payload,
            },
        )

    _event("LIVE_AUTO_TICK_STARTED", {"execution_mode": getattr(cfg, "execution_mode", ""), "enabled": bool(st.enabled)})

    if not bool(st.enabled):
        st.last_decision = "skipped"
        st.last_reason = "auto_guarded_not_started"
        store.upsert(st)
        return {"ok": True, "skipped": True, "reason": st.last_reason, "state": asdict(st)}

    if str(getattr(cfg, "execution_mode", "")).strip().lower() != "live_auto_guarded":
        st.last_decision = "blocked"
        st.last_reason = "EXECUTION_MODE is not live_auto_guarded"
        _event("LIVE_AUTO_EMERGENCY_STOP_BLOCKED", {"reason": st.last_reason, "blockers": ["wrong_execution_mode"]})
        store.upsert(st)
        return {"ok": False, "error": "wrong_execution_mode", "state": asdict(st)}

    if not bool(getattr(cfg, "live_auto_order", False)):
        st.last_decision = "blocked"
        st.last_reason = "LIVE_AUTO_ORDER is not true"
        _event("LIVE_AUTO_BUY_REJECTED", {"reason": st.last_reason, "blockers": ["LIVE_AUTO_ORDER_OFF"]})
        store.upsert(st)
        return {"ok": True, "skipped": True, "reason": st.last_reason, "state": asdict(st)}

    if not orders_allowed:
        st.last_decision = "blocked_before_order"
        st.last_reason = "runtime_safety_validation failed"
        bdetails = list(safety.get("blocker_details") or [])
        if any("EMERGENCY_STOP" in str(x) or "emergency stop" in str(x).lower() for x in safety_blockers):
            _event(
                "LIVE_AUTO_EMERGENCY_STOP_BLOCKED",
                {"reason": st.last_reason, "blockers": safety_blockers, "blocker_details": bdetails},
            )
        _event("LIVE_AUTO_BUY_REJECTED", {"reason": st.last_reason, "blockers": safety_blockers, "blocker_details": bdetails})
        store.upsert(st)

    if orders_allowed:
        cds, cd_reason = should_skip_due_to_cooldown(cooldown_until_utc=st.cooldown_until_utc)
        if cds:
            st.last_decision = "skipped"
            st.last_reason = cd_reason
            _event("LIVE_AUTO_COOLDOWN_ACTIVE", {"reason": st.last_reason})
            store.upsert(st)
            return {"ok": True, "skipped": True, "reason": st.last_reason, "state": asdict(st)}

        ok_open, open_reason = _market_open_ok(bool(getattr(cfg, "live_auto_require_market_open", True)))
        if not ok_open:
            st.last_decision = "skipped"
            st.last_reason = open_reason
            store.upsert(st)
            return {"ok": True, "skipped": True, "reason": st.last_reason, "state": asdict(st)}

    try:
        app_key, app_secret, account_no, product_code, mode = broker_service.get_plain_credentials(user_id)
    except Exception:
        st.last_decision = "blocked_before_order" if blocked_before_order else "blocked"
        st.last_reason = "broker_credentials_missing"
        store.upsert(st)
        if blocked_before_order:
            return {
                "ok": True,
                "blocked_before_order": True,
                "safety_blockers": safety_blockers,
                "safety": safety,
                "reason": st.last_reason,
                "error": st.last_reason,
                "state": asdict(st),
                "submitted": {"sells": [], "buys": []},
                "pnl": None,
                "counts": {"positions": 0, "open_orders": 0, "fills": 0},
                "candidate_count": 0,
                "evaluated_candidates": [],
                "fetch_summary": [],
                "last_diagnostics": [],
                "rejection_reasons_by_symbol": {},
                "market_mode": None,
            }
        return {"ok": False, "error": "broker_credentials_missing", "state": asdict(st)}

    if (mode or "").strip().lower() != "live":
        st.last_decision = "blocked"
        st.last_reason = "broker_account_not_live"
        store.upsert(st)
        return {"ok": False, "error": "broker_account_not_live", "state": asdict(st)}

    tok = broker_service.ensure_cached_token_for_paper_start(user_id)
    if not getattr(tok, "ok", False) or not getattr(tok, "access_token", ""):
        st.last_decision = "blocked"
        st.last_reason = getattr(tok, "failure_code", None) or "token_not_ready"
        store.upsert(st)
        return {"ok": False, "error": st.last_reason, "state": asdict(st)}

    api_base = broker_service._resolve_kis_api_base(mode)  # type: ignore[attr-defined]
    if not _is_live_base_url(str(api_base or "")):
        st.last_decision = "blocked"
        st.last_reason = f"invalid_live_base_url base={api_base}"
        store.upsert(st)
        return {"ok": False, "error": "invalid_live_base_url", "state": asdict(st)}

    client = build_kis_client_for_live_user(
        base_url=str(api_base),
        access_token=str(getattr(tok, "access_token")),
        app_key=str(app_key),
        app_secret=str(app_secret),
        live_execution_unlocked=bool(orders_allowed),
    )
    broker = _build_live_broker(
        cfg=cfg,
        client=client,
        account_no=account_no,
        product_code=product_code,
        read_only=bool(blocked_before_order),
    )

    positions = broker.get_positions()
    open_orders = broker.get_open_orders()
    fills = broker.get_fills()
    cash = float(broker.get_cash() or 0.0)

    latest_prices: dict[str, float] = {}
    for p in positions:
        sym = str(getattr(p, "symbol", "") or "")
        if not sym:
            continue
        try:
            q = client.get_quote(sym)
            latest_prices[sym] = _safe_price_from_quote(q)
        except Exception:
            latest_prices[sym] = float(getattr(p, "average_price", 0.0) or 0.0)

    total_mv = 0.0
    mv_by_symbol: dict[str, float] = {}
    for p in positions:
        sym = str(getattr(p, "symbol", "") or "")
        q = int(getattr(p, "quantity", 0) or 0)
        if not sym or q <= 0:
            continue
        px = float(latest_prices.get(sym) or float(getattr(p, "average_price", 0.0) or 0.0))
        mv = float(px) * float(q)
        mv_by_symbol[sym] = mv
        total_mv += mv

    equity = float(cash) + float(total_mv)
    eq_tracker = EquityTracker(_equity_tracker_path(cfg, user_id))
    daily_pct, total_pct = eq_tracker.pnl_snapshot(equity, valid=True)

    if float(daily_pct) <= -abs(float(getattr(cfg, "live_auto_daily_loss_limit_pct", 2.0))):
        st.last_decision = "risk_off"
        st.last_reason = f"daily_loss_limit_hit daily_pnl_pct={daily_pct:.4f}"
        _event("LIVE_AUTO_DAILY_LOSS_LIMIT_HIT", {"daily_pnl_pct": float(daily_pct), "equity": equity})
        store.upsert(st)
        return {"ok": True, "skipped": True, "reason": st.last_reason, "state": asdict(st), "pnl": {"daily_pct": daily_pct, "total_pct": total_pct}}

    if float(total_pct) <= -abs(float(getattr(cfg, "live_auto_total_drawdown_limit_pct", 5.0))):
        st.last_decision = "risk_off"
        st.last_reason = f"total_drawdown_limit_hit total_pnl_pct={total_pct:.4f}"
        _event("LIVE_AUTO_TOTAL_DRAWDOWN_LIMIT_HIT", {"total_pnl_pct": float(total_pct), "equity": equity})
        store.upsert(st)
        return {"ok": True, "skipped": True, "reason": st.last_reason, "state": asdict(st), "pnl": {"daily_pct": daily_pct, "total_pct": total_pct}}

    sell_submitted: list[dict[str, Any]] = []
    if bool(getattr(cfg, "live_auto_sell_enabled", True)):
        for p in positions:
            sym = str(getattr(p, "symbol", "") or "")
            q = int(getattr(p, "quantity", 0) or 0)
            if not sym or q <= 0:
                continue
            avg = float(getattr(p, "average_price", 0.0) or 0.0)
            px = float(latest_prices.get(sym) or 0.0)
            decision = evaluate_exit_for_position(
                symbol=sym,
                quantity=q,
                average_price=avg,
                last_price=px,
                state=st.__dict__,
                stop_loss_enabled=bool(getattr(cfg, "live_auto_stop_loss_enabled", True)),
                take_profit_enabled=True,
                trailing_enabled=True,
            )
            if not decision.should_sell:
                continue
            if st.daily_sell_count >= int(getattr(cfg, "live_auto_max_daily_sell_count", 10)):
                _event("LIVE_AUTO_SELL_SUBMITTED", {"symbol": sym, "skipped": True, "reason": "daily_sell_limit_reached"})
                continue
            dup = _recent_dup_blocked(st, side="sell", symbol=sym, block_minutes=int(getattr(cfg, "live_auto_duplicate_order_block_minutes", 30)))
            if dup[0]:
                _event("LIVE_AUTO_SELL_SUBMITTED", {"symbol": sym, "skipped": True, "reason": dup[1]})
                continue
            order = OrderRequest(symbol=sym, side="sell", quantity=int(decision.quantity), price=0, strategy_id="live_auto_guarded", signal_reason=decision.reason)
            if not orders_allowed:
                _event("LIVE_AUTO_SELL_SUBMITTED", {"symbol": sym, "skipped": True, "reason": "blocked_before_order"})
                continue
            res = broker.place_order(order)
            st.daily_sell_count += 1
            st.recent_submits[_dup_key("sell", sym)] = _utc_now_iso()
            sell_submitted.append(
                {"symbol": sym, "quantity": int(decision.quantity), "accepted": bool(res.accepted), "order_id": res.order_id, "reason": decision.reason}
            )
            if "stop_loss" in decision.reason:
                set_cooldown_after_loss(state=st.__dict__, minutes=int(getattr(cfg, "live_auto_cooldown_after_loss_minutes", 30)))
                _event("LIVE_AUTO_STOP_LOSS_TRIGGERED", {"symbol": sym, "decision": asdict(decision), "order_id": res.order_id})
            elif "take_profit" in decision.reason:
                _event("LIVE_AUTO_TAKE_PROFIT_TRIGGERED", {"symbol": sym, "decision": asdict(decision), "order_id": res.order_id})
            elif "trailing_stop" in decision.reason:
                _event("LIVE_AUTO_TRAILING_STOP_TRIGGERED", {"symbol": sym, "decision": asdict(decision), "order_id": res.order_id})
            else:
                _event("LIVE_AUTO_SELL_SUBMITTED", {"symbol": sym, "decision": asdict(decision), "order_id": res.order_id})

    buy_submitted: list[dict[str, Any]] = []
    shadow_eval: dict[str, Any] | None = None
    if blocked_before_order:
        from backend.app.engine.live_prep_engine import generate_final_betting_shadow_candidates

        manual = LiveMarketModeStore(getattr(cfg, "live_market_mode_store_json")).get(user_id, market="domestic")
        try:
            shadow_eval = generate_final_betting_shadow_candidates(
                broker_service=broker_service,
                backend_settings=cfg,
                user_id=user_id,
                limit=5,
                manual_market_mode=manual,
            )
        except Exception as exc:
            shadow_eval = {
                "ok": False,
                "error": "shadow_eval_failed",
                "message": str(exc),
                "candidate_count": 0,
                "candidates": [],
                "shadow": {"fetch_summary": [], "last_diagnostics": [], "rejection_reasons_by_symbol": {}},
            }

    if bool(getattr(cfg, "live_auto_buy_enabled", False)):
        if st.daily_buy_count < int(getattr(cfg, "live_auto_max_daily_buy_count", 3)):
            if len(positions) < int(getattr(cfg, "live_auto_max_position_count", 5)):
                if (cash - float(getattr(cfg, "live_auto_min_cash_buffer_krw", 100_000.0))) > float(getattr(cfg, "live_auto_max_order_krw", 100_000.0)):
                    from backend.app.engine.live_prep_engine import generate_final_betting_shadow_candidates

                    manual = LiveMarketModeStore(getattr(cfg, "live_market_mode_store_json")).get(user_id, market="domestic")
                    shadow = generate_final_betting_shadow_candidates(
                        broker_service=broker_service,
                        backend_settings=cfg,
                        user_id=user_id,
                        limit=5,
                        manual_market_mode=manual,
                    )
                    shadow_eval = shadow if isinstance(shadow, dict) else shadow_eval
                    candidates = list(shadow.get("candidates") or []) if isinstance(shadow, dict) else []
                    perf_by_strategy: dict[str, dict[str, Any]] = {}
                    perf_by_symbol: dict[tuple[str, str], dict[str, Any]] = {}
                    best = None
                    best_score = -999.0
                    best_reason = ""
                    for c in candidates:
                        sym = str(c.get("symbol") or "")
                        side = str(c.get("side") or "").lower()
                        if side != "buy" or not sym:
                            continue
                        sid = str(c.get("strategy_id") or "").strip() or "final_betting_v1"
                        already = any(str(getattr(p, "symbol", "")) == sym for p in positions)
                        has_oo = any(getattr(o, "symbol", "") == sym and getattr(o, "side", "") == "buy" for o in open_orders)
                        price = c.get("price")
                        base = None
                        try:
                            flow = float(c.get("score")) if c.get("score") is not None else None
                        except Exception:
                            flow = None
                        if flow is not None:
                            base = (float(flow) - 50.0) / 50.0
                        if sid not in perf_by_strategy:
                            try:
                                sig = get_performance_signal(cfg, strategy_id=sid, lookback_days=60, min_sell_trades=10)
                                perf_by_strategy[sid] = {
                                    "score_adjustment": sig.score_adjustment,
                                    "buy_blocked": sig.buy_blocked,
                                    "reason": sig.reason,
                                    "metrics": sig.metrics,
                                }
                            except Exception:
                                perf_by_strategy[sid] = {"score_adjustment": 0.0, "buy_blocked": False, "reason": "perf_unavailable"}
                        k = (sid, sym)
                        if k not in perf_by_symbol:
                            try:
                                sigs = get_performance_signal(cfg, strategy_id=sid, symbol=sym, lookback_days=120, min_sell_trades=5)
                                perf_by_symbol[k] = {
                                    "score_adjustment": sigs.score_adjustment,
                                    "buy_blocked": sigs.buy_blocked,
                                    "reason": sigs.reason,
                                    "metrics": sigs.metrics,
                                }
                            except Exception:
                                perf_by_symbol[k] = {"score_adjustment": 0.0, "buy_blocked": False, "reason": "symbol_perf_unavailable"}
                        ps = perf_by_strategy.get(sid) or {}
                        pxs = perf_by_symbol.get(k) or {}
                        perf_bundle = {
                            "score_adjustment": float(ps.get("score_adjustment") or 0.0) + float(pxs.get("score_adjustment") or 0.0),
                            "buy_blocked": bool(ps.get("buy_blocked")) or bool(pxs.get("buy_blocked")),
                            "reason": f"strategy({ps.get('reason','')}) | symbol({pxs.get('reason','')})"[:700],
                            "metrics": {"strategy": ps.get("metrics"), "symbol": pxs.get("metrics")},
                        }
                        sc = score_candidate(
                            symbol=sym,
                            base_signal_score=base,
                            order_price=float(price) if price is not None else None,
                            market_mode=shadow.get("market_mode") if isinstance(shadow, dict) else None,
                            already_holding=already,
                            has_open_order=has_oo,
                            strategy_performance=perf_bundle,
                        )
                        if sc.score > best_score:
                            best_score = sc.score
                            best = c
                            best_reason = sc.reason
                    if best is not None and best_score >= 0.5:
                        sym = str(best.get("symbol") or "")
                        px = best.get("price")
                        try:
                            px_f = float(px) if px is not None else 0.0
                        except Exception:
                            px_f = 0.0
                        qty = int(best.get("quantity") or 0)
                        if qty <= 0:
                            qty = 1
                        est_cost = float(px_f) * float(qty) if px_f > 0 else float(getattr(cfg, "live_auto_max_order_krw", 100_000.0))
                        exposure_ctx = {
                            "order_est_cost_krw": float(est_cost),
                            "order_price": (None if px_f <= 0 else float(px_f)),
                            "quantity": int(qty),
                            "cash": float(cash),
                            "cash_buffer_krw": float(getattr(cfg, "live_auto_min_cash_buffer_krw", 100_000.0)),
                            "symbol_mv_krw": float(mv_by_symbol.get(sym, 0.0)),
                            "total_mv_krw": float(total_mv),
                            "max_order_krw": float(getattr(cfg, "live_auto_max_order_krw", 100_000.0)),
                            "max_symbol_exposure_krw": float(getattr(cfg, "live_auto_max_symbol_exposure_krw", 300_000.0)),
                            "max_total_exposure_krw": float(getattr(cfg, "live_auto_max_total_exposure_krw", 1_000_000.0)),
                        }
                        if est_cost > float(getattr(cfg, "live_auto_max_order_krw", 100_000.0)):
                            _event("LIVE_AUTO_BUY_REJECTED", {"symbol": sym, "reason": "max_order_krw_exceeded", "score": best_score, **exposure_ctx})
                        elif (mv_by_symbol.get(sym, 0.0) + est_cost) > float(getattr(cfg, "live_auto_max_symbol_exposure_krw", 300_000.0)):
                            _event("LIVE_AUTO_BUY_REJECTED", {"symbol": sym, "reason": "max_symbol_exposure_exceeded", "score": best_score, **exposure_ctx})
                        elif (total_mv + est_cost) > float(getattr(cfg, "live_auto_max_total_exposure_krw", 1_000_000.0)):
                            _event("LIVE_AUTO_BUY_REJECTED", {"symbol": sym, "reason": "max_total_exposure_exceeded", "score": best_score, **exposure_ctx})
                        else:
                            blocked, bwhy = _recent_dup_blocked(
                                st,
                                side="buy",
                                symbol=sym,
                                block_minutes=int(getattr(cfg, "live_auto_duplicate_order_block_minutes", 30)),
                            )
                            if blocked:
                                _event("LIVE_AUTO_BUY_REJECTED", {"symbol": sym, "reason": bwhy, "score": best_score, **exposure_ctx})
                            else:
                                order = OrderRequest(
                                    symbol=sym,
                                    side="buy",
                                    quantity=int(qty),
                                    price=0 if px_f <= 0 else float(px_f),
                                    strategy_id="live_auto_guarded",
                                    signal_reason=f"auto_buy score={best_score:.3f} | {best_reason}",
                                )
                                if not orders_allowed:
                                    _event("LIVE_AUTO_BUY_REJECTED", {"symbol": sym, "reason": "blocked_before_order", "score": best_score, **exposure_ctx})
                                else:
                                    res = broker.place_order(order)
                                    st.daily_buy_count += 1
                                    st.recent_submits[_dup_key("buy", sym)] = _utc_now_iso()
                                    buy_submitted.append(
                                        {
                                            "symbol": sym,
                                            "quantity": int(qty),
                                            "accepted": bool(res.accepted),
                                            "order_id": res.order_id,
                                            "score": best_score,
                                        }
                                    )
                                    _event(
                                        "LIVE_AUTO_BUY_SUBMITTED",
                                        {"symbol": sym, "order_id": res.order_id, "score": best_score, "quantity": int(qty), **exposure_ctx},
                                    )
                    else:
                        _event("LIVE_AUTO_BUY_REJECTED", {"reason": "no_candidate_above_threshold", "best_score": float(best_score)})
                else:
                    _event("LIVE_AUTO_BUY_REJECTED", {"reason": "cash_buffer_or_max_order_krw_blocked", "cash": cash})
            else:
                _event("LIVE_AUTO_BUY_REJECTED", {"reason": "max_position_count_reached", "position_count": len(positions)})
        else:
            _event("LIVE_AUTO_BUY_REJECTED", {"reason": "daily_buy_limit_reached", "daily_buy_count": st.daily_buy_count})

    cd_after = int(getattr(cfg, "live_auto_cooldown_after_order_seconds", 60) or 0)
    if cd_after > 0 and (sell_submitted or buy_submitted):
        until = datetime.now(timezone.utc) + timedelta(seconds=cd_after)
        st.cooldown_until_utc = until.isoformat()

    st.last_decision = "ok"
    st.last_reason = f"sell_submitted={len(sell_submitted)} buy_submitted={len(buy_submitted)}"
    store.upsert(st)
    _event(
        "LIVE_AUTO_TICK_FINISHED",
        {
            "sell_submitted": sell_submitted,
            "buy_submitted": buy_submitted,
            "pnl": {"daily_pct": float(daily_pct), "total_pct": float(total_pct), "equity": equity},
        },
    )
    return {
        "ok": True,
        "blocked_before_order": bool(blocked_before_order),
        "safety_blockers": safety_blockers,
        "safety": safety,
        "state": asdict(st),
        "submitted": {"sells": sell_submitted, "buys": buy_submitted},
        "pnl": {"daily_pct": float(daily_pct), "total_pct": float(total_pct), "equity": equity},
        "counts": {"positions": len(positions), "open_orders": len(open_orders), "fills": len(fills)},
        "candidate_count": int((shadow_eval or {}).get("candidate_count") or 0) if isinstance(shadow_eval, dict) else 0,
        "evaluated_candidates": list((shadow_eval or {}).get("candidates") or []) if isinstance(shadow_eval, dict) else [],
        "fetch_summary": (
            list(((shadow_eval or {}).get("shadow") or {}).get("fetch_summary") or [])
            if isinstance(shadow_eval, dict)
            else []
        ),
        "last_diagnostics": (
            list(((shadow_eval or {}).get("shadow") or {}).get("last_diagnostics") or [])
            if isinstance(shadow_eval, dict)
            else []
        ),
        "rejection_reasons_by_symbol": (
            dict(((shadow_eval or {}).get("shadow") or {}).get("rejection_reasons_by_symbol") or {})
            if isinstance(shadow_eval, dict)
            else {}
        ),
        "market_mode": (shadow_eval or {}).get("market_mode") if isinstance(shadow_eval, dict) else None,
    }

