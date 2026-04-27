from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.core.config import BackendSettings, get_backend_settings
from backend.app.risk.audit import append_risk_event
from backend.app.services.live_exec_session_store import LiveExecSession, LiveExecSessionStore
from backend.app.services.live_market_mode_store import LiveMarketModeStore
from backend.app.services.live_auto_guarded_store import LiveAutoGuardedStore

from .auth_routes import get_current_user_from_auth_header
from .broker_routes import get_broker_service
from .live_trading_routes import runtime_safety_validation_for_user_id
from ..engine.live_prep_engine import generate_final_betting_shadow_candidates, generate_intraday_shadow_report
from ..engine.live_auto_guarded_engine import tick_live_auto_guarded
from ..engine.live_auto_guarded_loop import (
    get_live_auto_guarded_loop_status,
    start_live_auto_guarded_loop,
    stop_live_auto_guarded_loop,
)
from ..services.live_prep_store import LiveCandidate, LiveCandidateStore

router = APIRouter(prefix="/live-exec", tags=["live-exec"])

LiveMarket = Literal["domestic"]


class LiveExecStartRequest(BaseModel):
    strategy_id: str = Field(min_length=3, max_length=80)
    market: LiveMarket = "domestic"
    execution_mode: Literal["live_shadow", "live_manual_approval"]
    actor: str = Field(default="user", min_length=1, max_length=64)
    reason: str = Field(default="start_live_session", min_length=3, max_length=240)


class LiveExecStopRequest(BaseModel):
    actor: str = Field(default="user", min_length=1, max_length=64)
    reason: str = Field(default="stop_live_session", min_length=3, max_length=240)


class LiveAutoGuardedStartRequest(BaseModel):
    actor: str = Field(default="user", min_length=1, max_length=64)
    reason: str = Field(default="start_live_auto_guarded", min_length=3, max_length=240)


class LiveAutoGuardedStopRequest(BaseModel):
    actor: str = Field(default="user", min_length=1, max_length=64)
    reason: str = Field(default="stop_live_auto_guarded", min_length=3, max_length=240)


def _store(cfg: BackendSettings) -> LiveExecSessionStore:
    return LiveExecSessionStore(cfg.live_exec_sessions_store_json)

def _auto_store(cfg: BackendSettings) -> LiveAutoGuardedStore:
    return LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json)


def _candidate_store(cfg: BackendSettings) -> LiveCandidateStore:
    return LiveCandidateStore(cfg.live_prep_candidates_store_json)


def _current_user(authorization: str | None) -> Any:
    u = get_current_user_from_auth_header(authorization)
    if not u:
        raise HTTPException(status_code=401, detail="unauthorized")
    return u


def _supported_strategies() -> list[str]:
    return ["final_betting_v1", "scalp_rsi_flag_hf_v1", "scalp_macd_rsi_3m_v1", "swing_relaxed_v2"]


def _validate_combo(strategy_id: str, execution_mode: str) -> list[str]:
    blockers: list[str] = []
    sid = (strategy_id or "").strip()
    mode = (execution_mode or "").strip().lower()
    if sid not in set(_supported_strategies()):
        blockers.append(f"unsupported strategy_id: {sid}")
    if mode not in {"live_shadow", "live_manual_approval"}:
        blockers.append(f"unsupported execution_mode: {mode}")
    if mode == "live_manual_approval" and sid != "final_betting_v1":
        blockers.append("intraday strategies must run in live_shadow (manual approval not allowed by default)")
    return blockers


def _start_blockers(cfg: BackendSettings, strategy_id: str, execution_mode: str) -> list[str]:
    blockers: list[str] = []
    if (cfg.trading_mode or "").strip().lower() != "live":
        blockers.append("TRADING_MODE is not live")
    blockers.extend(_validate_combo(strategy_id, execution_mode))
    return blockers


@router.get("/status")
def live_exec_status(
    authorization: str | None = Header(default=None),
    include_history: bool = Query(default=False),
) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    st = _store(cfg)
    active = st.get_active(user.id)
    latest = st.get_latest(user.id)
    safety = runtime_safety_validation_for_user_id(cfg, user.id)

    candidate_store = _candidate_store(cfg)
    pending = candidate_store.list_filtered(status="approval_pending", strategy_id="final_betting_v1", limit=200)
    running_candidates = candidate_store.list_filtered(status="candidate", strategy_id="final_betting_v1", limit=200)

    start_sid = (active.strategy_id if active else (latest.strategy_id if latest else "final_betting_v1"))
    start_mode = (active.execution_mode if active else (latest.execution_mode if latest else "live_shadow"))

    payload: dict[str, Any] = {
        "ok": True,
        "config": {
            "trading_mode": cfg.trading_mode,
            "execution_mode_env": cfg.execution_mode,
        },
        "safety": safety,
        "session": asdict(active) if active is not None else (asdict(latest) if latest is not None else None),
        "session_running": active is not None,
        "supported_strategies": _supported_strategies(),
        "counts": {
            "final_betting_candidates": len(running_candidates),
            "final_betting_pending_approvals": len(pending),
        },
        "blocked": {
            "start_blockers": _start_blockers(
                cfg,
                start_sid,
                start_mode,
            ),
            "submit_blockers": list(safety.get("blockers") or []),
            "submit_blocker_details": list(safety.get("blocker_details") or []),
        },
    }
    if include_history:
        payload["history"] = [asdict(x) for x in st.list_by_user(user.id, limit=20)]
    return payload


@router.post("/start")
def live_exec_start(payload: LiveExecStartRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    blockers = _start_blockers(cfg, payload.strategy_id, payload.execution_mode)
    if blockers:
        raise HTTPException(status_code=403, detail={"error": "start_blocked", "blockers": blockers})

    st = _store(cfg)
    existing = st.get_active(user.id)
    if existing is not None:
        raise HTTPException(status_code=409, detail={"error": "already_running", "session": asdict(existing)})

    now = datetime.now(timezone.utc).isoformat()
    sess = LiveExecSession(
        session_id=st.new_id(),
        user_id=user.id,
        status="running",
        strategy_id=str(payload.strategy_id),
        market=str(payload.market),
        execution_mode=str(payload.execution_mode),
        started_at_utc=now,
        actor=str(payload.actor or user.id),
        reason=str(payload.reason or "start_live_session"),
    )
    st.upsert(sess)
    append_risk_event(
        cfg.risk_events_jsonl,
        {
            "ts_utc": now,
            "event_type": "LIVE_EXEC_SESSION_STARTED",
            "actor": user.id,
            "strategy_id": sess.strategy_id,
            "market": sess.market,
            "execution_mode": sess.execution_mode,
            "reason": sess.reason,
        },
    )
    return {"ok": True, "session": asdict(sess)}


@router.post("/stop")
def live_exec_stop(payload: LiveExecStopRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    st = _store(cfg)
    existing = st.get_active(user.id)
    if existing is None:
        return {"ok": True, "stopped": False, "message": "already_stopped"}

    existing.status = "stopped"
    existing.stopped_at_utc = datetime.now(timezone.utc).isoformat()
    existing.actor = str(payload.actor or user.id)
    existing.reason = str(payload.reason or "stop_live_session")
    st.upsert(existing)
    append_risk_event(
        cfg.risk_events_jsonl,
        {
            "ts_utc": existing.stopped_at_utc,
            "event_type": "LIVE_EXEC_SESSION_STOPPED",
            "actor": user.id,
            "strategy_id": existing.strategy_id,
            "market": existing.market,
            "execution_mode": existing.execution_mode,
            "reason": existing.reason,
        },
    )
    return {"ok": True, "stopped": True, "session": asdict(existing)}


@router.post("/tick")
def live_exec_tick(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    st = _store(cfg)
    sess = st.get_active(user.id)
    if sess is None:
        raise HTTPException(status_code=409, detail={"error": "not_running"})

    manual_mode = LiveMarketModeStore(cfg.live_market_mode_store_json).get(user.id, market=str(sess.market or "domestic"))
    try:
        svc = get_broker_service()
        if sess.strategy_id == "final_betting_v1":
            out = generate_final_betting_shadow_candidates(
                broker_service=svc,
                backend_settings=cfg,
                user_id=user.id,
                limit=5,
                manual_market_mode=manual_mode,
            )
        else:
            out = generate_intraday_shadow_report(
                broker_service=svc,
                backend_settings=cfg,
                user_id=user.id,
                strategy_id=sess.strategy_id,
                manual_market_mode=manual_mode,
            )
    except Exception as exc:
        sess.last_error = str(exc)
        sess.last_tick_at_utc = datetime.now(timezone.utc).isoformat()
        st.upsert(sess)
        raise

    sess.last_tick_at_utc = datetime.now(timezone.utc).isoformat()
    sess.last_tick_summary = {
        "ok": bool(out.get("ok")),
        "strategy_id": sess.strategy_id,
        "execution_mode": sess.execution_mode,
        "market": sess.market,
    }
    st.upsert(sess)

    cstore = _candidate_store(cfg)
    if sess.strategy_id == "final_betting_v1" and bool(out.get("ok")):
        items: list[LiveCandidate] = []
        for row in list(out.get("candidates") or []):
            try:
                cand = LiveCandidate(**row)
            except TypeError:
                continue
            cstore.upsert(cand)
            items.append(cand)
        if items:
            append_risk_event(
                cfg.risk_events_jsonl,
                {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "event_type": "LIVE_EXEC_FINAL_BETTING_CANDIDATES_UPSERTED",
                    "actor": user.id,
                    "count": len(items),
                },
            )
    pending = cstore.list_filtered(status="approval_pending", strategy_id="final_betting_v1", limit=200)
    candidates = cstore.list_filtered(status="candidate", strategy_id="final_betting_v1", limit=200)

    return {
        "ok": True,
        "session": asdict(sess),
        "result": out,
        "counts": {
            "final_betting_candidates": len(candidates),
            "final_betting_pending_approvals": len(pending),
        },
    }


@router.get("/auto-guarded/status")
def live_auto_guarded_status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    safety = runtime_safety_validation_for_user_id(cfg, user.id)
    st = _auto_store(cfg).get(user.id)
    can_auto_order = (
        (cfg.trading_mode or "").strip().lower() == "live"
        and (cfg.execution_mode or "").strip().lower() == "live_auto_guarded"
        and bool(cfg.live_auto_order)
        and bool(safety.get("ok"))
        and bool(getattr(cfg, "live_trading", False) or getattr(cfg, "live_trading_enabled", False))
        and bool(getattr(cfg, "live_trading_confirm", False))
        and bool(getattr(cfg, "live_trading_extra_confirm", False))
    )
    loop_status = get_live_auto_guarded_loop_status(user.id)
    return {
        "ok": True,
        "config": {
            "trading_mode": cfg.trading_mode,
            "execution_mode_env": cfg.execution_mode,
            "live_auto_order": bool(cfg.live_auto_order),
            "live_auto_buy_enabled": bool(getattr(cfg, "live_auto_buy_enabled", False)),
            "live_auto_sell_enabled": bool(getattr(cfg, "live_auto_sell_enabled", True)),
            "live_auto_stop_loss_enabled": bool(getattr(cfg, "live_auto_stop_loss_enabled", True)),
            "live_auto_loop_enabled": bool(getattr(cfg, "live_auto_loop_enabled", False)),
            "live_auto_loop_interval_sec": int(getattr(cfg, "live_auto_loop_interval_sec", 60)),
            "live_auto_loop_max_consecutive_failures": int(getattr(cfg, "live_auto_loop_max_consecutive_failures", 5)),
            "live_auto_loop_auto_resume": bool(getattr(cfg, "live_auto_loop_auto_resume", False)),
            "limits": {
                "max_order_krw": float(getattr(cfg, "live_auto_max_order_krw", 0.0)),
                "max_daily_buy_count": int(getattr(cfg, "live_auto_max_daily_buy_count", 0)),
                "max_daily_sell_count": int(getattr(cfg, "live_auto_max_daily_sell_count", 0)),
                "max_position_count": int(getattr(cfg, "live_auto_max_position_count", 0)),
                "max_symbol_exposure_krw": float(getattr(cfg, "live_auto_max_symbol_exposure_krw", 0.0)),
                "max_total_exposure_krw": float(getattr(cfg, "live_auto_max_total_exposure_krw", 0.0)),
                "daily_loss_limit_pct": float(getattr(cfg, "live_auto_daily_loss_limit_pct", 0.0)),
                "total_drawdown_limit_pct": float(getattr(cfg, "live_auto_total_drawdown_limit_pct", 0.0)),
                "min_cash_buffer_krw": float(getattr(cfg, "live_auto_min_cash_buffer_krw", 0.0)),
                "cooldown_after_loss_minutes": int(getattr(cfg, "live_auto_cooldown_after_loss_minutes", 0)),
                "cooldown_after_order_seconds": int(getattr(cfg, "live_auto_cooldown_after_order_seconds", 0)),
                "duplicate_order_block_minutes": int(getattr(cfg, "live_auto_duplicate_order_block_minutes", 0)),
                "require_market_open": bool(getattr(cfg, "live_auto_require_market_open", True)),
            },
        },
        "state": asdict(st),
        "loop": loop_status,
        "safety": safety,
        "can_place_auto_order": bool(can_auto_order and bool(st.enabled)),
        "can_tick": bool((cfg.trading_mode or "").strip().lower() == "live" and (cfg.execution_mode or "").strip().lower() == "live_auto_guarded"),
    }


@router.post("/auto-guarded/start")
def live_auto_guarded_start(payload: LiveAutoGuardedStartRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    if (cfg.trading_mode or "").strip().lower() != "live":
        raise HTTPException(status_code=403, detail="TRADING_MODE=live required")
    if (cfg.execution_mode or "").strip().lower() != "live_auto_guarded":
        raise HTTPException(status_code=403, detail="EXECUTION_MODE=live_auto_guarded required")
    sess = _store(cfg).get_active(user.id)
    if sess is not None:
        raise HTTPException(status_code=409, detail="live_exec_session_running")
    st = _auto_store(cfg).get(user.id)
    st.enabled = True
    st.started_at_utc = datetime.now(timezone.utc).isoformat()
    st.stopped_at_utc = None
    st.updated_at_utc = datetime.now(timezone.utc).isoformat()
    astore = _auto_store(cfg)
    astore.upsert(st)
    append_risk_event(
        cfg.risk_events_jsonl,
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "LIVE_AUTO_GUARDED_STARTED",
            "actor": user.id,
            "app_actor": payload.actor,
            "reason": payload.reason,
        },
    )
    loop_out: dict[str, Any] | None = None
    if bool(getattr(cfg, "live_auto_loop_enabled", False)):
        loop_out = start_live_auto_guarded_loop(cfg=cfg, broker_service=get_broker_service(), store=astore, user_id=user.id)
    return {"ok": True, "state": asdict(st), "loop": loop_out}


@router.post("/auto-guarded/stop")
def live_auto_guarded_stop(payload: LiveAutoGuardedStopRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    st = _auto_store(cfg).get(user.id)
    st.enabled = False
    st.stopped_at_utc = datetime.now(timezone.utc).isoformat()
    st.updated_at_utc = datetime.now(timezone.utc).isoformat()
    _auto_store(cfg).upsert(st)
    loop_out = stop_live_auto_guarded_loop(cfg=cfg, user_id=user.id, reason=payload.reason)
    append_risk_event(
        cfg.risk_events_jsonl,
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "LIVE_AUTO_GUARDED_STOPPED",
            "actor": user.id,
            "app_actor": payload.actor,
            "reason": payload.reason,
        },
    )
    return {"ok": True, "state": asdict(st), "loop": loop_out}


@router.post("/auto-guarded/tick")
def live_auto_guarded_tick(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    if (cfg.execution_mode or "").strip().lower() != "live_auto_guarded":
        raise HTTPException(status_code=403, detail="EXECUTION_MODE=live_auto_guarded required")
    safety = runtime_safety_validation_for_user_id(cfg, user.id)
    svc = get_broker_service()
    out = tick_live_auto_guarded(cfg=cfg, broker_service=svc, user_id=user.id, safety=safety)
    return out

