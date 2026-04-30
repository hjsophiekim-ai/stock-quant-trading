from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.risk.audit import append_risk_event
from backend.app.risk.live_unlock_gate import evaluate_paper_readiness, paper_readiness_data_health, paper_readiness_to_dict
from backend.app.engine.live_readiness_builder import (
    get_readiness_builder_loop_status,
    start_readiness_builder,
    stop_readiness_builder,
    tick_readiness_builder_once,
)
from backend.app.services.live_readiness_builder_store import LiveReadinessBuilderStore

from ..core.config import BackendSettings, get_backend_settings
from ..clients.kis_client import build_kis_client_for_live_user
from ..services.broker_secret_service import BrokerSecretService
from ..services.live_auto_guarded_state_store import LiveAutoGuardedState, LiveAutoGuardedStateStore, LiveAutoMode
from ..services.live_safety_state_store import LiveSafetyHistoryItem, LiveSafetyState, LiveSafetyStateStore
from ..services.live_market_mode_store import LiveMarketModeStore

from .auth_routes import get_current_user_from_auth_header
from .broker_routes import get_broker_service
from ..engine.live_prep_engine import (
    generate_final_betting_shadow_candidates,
    generate_intraday_shadow_report,
    generate_swing_shadow_report,
)
from app.strategy.intraday_common import kst_now, parse_krx_hhmm

router = APIRouter(prefix="/live-trading", tags=["live-trading"])


class LiveSettingsUpdateRequest(BaseModel):
    live_trading_flag: bool
    secondary_confirm_flag: bool
    extra_approval_flag: bool
    reason: str = Field(min_length=3, max_length=240)
    actor: str = Field(default="user", min_length=1, max_length=64)

_mock_daily_loss_pct: float = -1.4
_mock_total_loss_pct: float = -4.7


def _store(cfg: BackendSettings) -> LiveSafetyStateStore:
    return LiveSafetyStateStore(cfg.live_trading_safety_state_store_json)


def _mode_store(cfg: BackendSettings) -> LiveMarketModeStore:
    return LiveMarketModeStore(cfg.live_market_mode_store_json)


def _current_user(authorization: str | None) -> object:
    u = get_current_user_from_auth_header(authorization)
    if not u:
        raise HTTPException(status_code=401, detail="unauthorized")
    return u


def _kill_switch_payload() -> dict[str, object]:
    daily_exceeded = abs(_mock_daily_loss_pct) >= 3.0
    total_exceeded = abs(_mock_total_loss_pct) >= 10.0
    exceeded = daily_exceeded or total_exceeded
    state: Literal["NORMAL", "TRIGGERED", "COOLDOWN"] = "TRIGGERED" if exceeded else "NORMAL"
    return {
        "kill_switch_state": state,
        "daily_loss_pct": _mock_daily_loss_pct,
        "total_loss_pct": _mock_total_loss_pct,
        "daily_loss_limit_pct": 3.0,
        "total_loss_limit_pct": 10.0,
        "loss_limit_exceeded": exceeded,
        "message": "손실 제한 초과: LIVE 주문 차단" if exceeded else "정상 범위",
    }


def _status_payload_for_user(cfg: BackendSettings, st: LiveSafetyState) -> dict[str, object]:
    readiness = evaluate_paper_readiness(cfg)
    paper_ok = readiness.ok or readiness.bypassed
    ks = _kill_switch_payload()
    has_operator_intent = bool(getattr(st, "history", None)) and len(list(getattr(st, "history") or [])) > 0
    requested_live = st.live_trading_flag if has_operator_intent else bool(cfg.live_trading)
    requested_confirm = st.secondary_confirm_flag if has_operator_intent else bool(cfg.live_trading_confirm)
    requested_extra = st.extra_approval_flag if has_operator_intent else bool(cfg.live_trading_extra_confirm)
    effective_live_flag = bool(st.live_trading_flag or requested_live)
    effective_confirm_flag = bool(st.secondary_confirm_flag or requested_confirm)
    effective_extra_flag = bool(st.extra_approval_flag or requested_extra)
    can_place = (
        cfg.trading_mode == "live"
        and effective_live_flag
        and effective_confirm_flag
        and effective_extra_flag
        and (not st.live_emergency_stop)
        and cfg.live_trading
        and cfg.live_trading_confirm
        and cfg.live_trading_extra_confirm
        and paper_ok
        and (not bool(ks.get("loss_limit_exceeded")))
    )
    if not can_place:
        missing: list[str] = []
        if cfg.trading_mode != "live":
            missing.append("TRADING_MODE=live")
        if not bool(cfg.live_trading):
            missing.append("ENV LIVE_TRADING=true")
        if not bool(cfg.live_trading_confirm):
            missing.append("ENV LIVE_TRADING_CONFIRM=true")
        if not bool(cfg.live_trading_extra_confirm):
            missing.append("ENV LIVE_TRADING_EXTRA_CONFIRM=true")
        if not bool(effective_live_flag):
            missing.append("APP live_trading_flag=true")
        if not bool(effective_confirm_flag):
            missing.append("APP secondary_confirm_flag=true")
        if not bool(effective_extra_flag):
            missing.append("APP extra_approval_flag=true")
        if missing:
            warning = "LIVE 주문 잠금 상태: 아래 항목이 필요합니다.\n- " + "\n- ".join(missing)
        elif not paper_ok:
            warning = readiness.user_message_ko
        elif bool(ks.get("loss_limit_exceeded")):
            warning = str(ks.get("message") or "손실 제한 초과")
        else:
            warning = "LIVE 주문 잠금 상태"
    else:
        warning = "LIVE 주문 가능 상태 (모든 승인·모의 검증 완료)"
    return {
        "trading_mode": cfg.trading_mode,
        "execution_mode": cfg.execution_mode,
        "live_unlock_bypass_requested": bool(getattr(cfg, "live_unlock_bypass", False)),
        "live_unlock_bypass_confirm_env": bool(getattr(cfg, "live_unlock_bypass_confirm", False)),
        "live_unlock_bypass_effective": bool(getattr(readiness, "bypassed", False)),
        "live_unlock_technical_summary": str(getattr(readiness, "technical_summary", "") or ""),
        "env_live_trading": bool(cfg.live_trading),
        "env_live_trading_confirm": bool(cfg.live_trading_confirm),
        "env_live_trading_extra_confirm": bool(cfg.live_trading_extra_confirm),
        "operator_intent_has_history": bool(has_operator_intent),
        "live_trading_flag": st.live_trading_flag,
        "secondary_confirm_flag": st.secondary_confirm_flag,
        "extra_approval_flag": st.extra_approval_flag,
        "effective_live_trading_flag": bool(effective_live_flag),
        "effective_secondary_confirm_flag": bool(effective_confirm_flag),
        "effective_extra_approval_flag": bool(effective_extra_flag),
        "requested_live_trading_flag": bool(requested_live),
        "requested_secondary_confirm_flag": bool(requested_confirm),
        "requested_extra_approval_flag": bool(requested_extra),
        "live_emergency_stop": st.live_emergency_stop,
        "paper_readiness_ok": paper_ok,
        "can_place_live_order": can_place,
        "effective_can_place_live_order": can_place,
        "unlock_pending_due_to_paper_readiness": bool(
            st.live_trading_flag and st.secondary_confirm_flag and st.extra_approval_flag and (not paper_ok)
        ),
        "trading_badge": "live" if can_place else "test",
        "warning_message": warning,
    }


@router.get("/status")
def live_status(authorization: str | None = Header(default=None)) -> dict[str, object]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    st = _store(cfg).get(getattr(user, "id"))
    status_payload = _status_payload_for_user(cfg, st)
    safety = runtime_safety_validation_for_user_id(cfg, getattr(user, "id"))
    settings_saved_but_not_effective = bool(
        bool(status_payload.get("unlock_pending_due_to_paper_readiness")) and (not bool(status_payload.get("can_place_live_order")))
    )
    return {
        **status_payload,
        "settings_saved_but_not_effective": settings_saved_but_not_effective,
        "pending_blockers": list(safety.get("blockers") or []),
        "pending_blocker_details": list(safety.get("blocker_details") or []),
    }


def _attempting_full_app_unlock(req: LiveSettingsUpdateRequest) -> bool:
    return bool(req.live_trading_flag and req.secondary_confirm_flag and req.extra_approval_flag)


@router.post("/settings")
def update_live_settings(
    payload: LiveSettingsUpdateRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    store = _store(cfg)
    st = store.get(getattr(user, "id"))
    attempting_full = _attempting_full_app_unlock(payload)
    st.live_trading_flag = bool(payload.live_trading_flag)
    st.secondary_confirm_flag = bool(payload.secondary_confirm_flag)
    st.extra_approval_flag = bool(payload.extra_approval_flag)
    st.updated_at_utc = datetime.now(timezone.utc).isoformat()
    st.history.insert(
        0,
        LiveSafetyHistoryItem(
            ts=st.updated_at_utc,
            actor=str(payload.actor or getattr(user, "id")),
            action="update_live_safety_settings",
            reason=str(payload.reason),
        ),
    )
    st.history = st.history[:100]
    store.upsert(st)

    unlock_pending_due_to_paper_readiness = False
    if attempting_full:
        pr = evaluate_paper_readiness(cfg)
        if not pr.ok and not pr.bypassed:
            unlock_pending_due_to_paper_readiness = True
            append_risk_event(
                cfg.risk_events_jsonl,
                {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "event_type": "LIVE_UNLOCK_PENDING_PAPER_READINESS",
                    "actor": getattr(user, "id"),
                    "app_actor": payload.actor,
                    "reason": payload.reason,
                    "paper_readiness": pr.technical_summary,
                    "user_message_ko": pr.user_message_ko,
                },
            )
            st.history.insert(
                0,
                LiveSafetyHistoryItem(
                    ts=datetime.now(timezone.utc).isoformat(),
                    actor=str(payload.actor or getattr(user, "id")),
                    action="live_unlock_pending_paper_readiness",
                    reason=f"{payload.reason} | {pr.user_message_ko[:200]}",
                ),
            )
            st.history = st.history[:100]
            st.updated_at_utc = datetime.now(timezone.utc).isoformat()
            store.upsert(st)
        else:
            append_risk_event(
                cfg.risk_events_jsonl,
                {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "event_type": "LIVE_UNLOCK_APPROVED_CHECKLIST",
                    "actor": getattr(user, "id"),
                    "app_actor": payload.actor,
                    "reason": payload.reason,
                    "paper_readiness": pr.technical_summary,
                },
            )

    status_payload = _status_payload_for_user(cfg, st)
    safety = runtime_safety_validation_for_user_id(cfg, getattr(user, "id"))
    settings_saved_but_not_effective = bool(unlock_pending_due_to_paper_readiness and (not bool(status_payload.get("can_place_live_order"))))

    return {
        "ok": True,
        "settings_saved": True,
        "unlock_pending_due_to_paper_readiness": bool(unlock_pending_due_to_paper_readiness),
        "settings_saved_but_not_effective": settings_saved_but_not_effective,
        "pending_blockers": list(safety.get("blockers") or []),
        "pending_blocker_details": list(safety.get("blocker_details") or []),
        **status_payload,
    }


@router.get("/settings-history")
def settings_history(authorization: str | None = Header(default=None)) -> dict[str, object]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    st = _store(cfg).get(getattr(user, "id"))
    return {"items": [item.__dict__ for item in st.history]}


@router.get("/paper-readiness")
def paper_readiness(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _ = _current_user(authorization)
    cfg = get_backend_settings()
    pr = evaluate_paper_readiness(cfg)
    return {
        **paper_readiness_to_dict(pr),
        "data_health": paper_readiness_data_health(cfg),
    }


@router.get("/paper-readiness-diagnostics")
def paper_readiness_diagnostics(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _ = _current_user(authorization)
    cfg = get_backend_settings()
    return paper_readiness_data_health(cfg)


def _readiness_store(cfg: BackendSettings) -> LiveReadinessBuilderStore:
    return LiveReadinessBuilderStore(getattr(cfg, "readiness_builder_state_store_json"))


@router.get("/readiness-builder/status")
def readiness_builder_status(
    authorization: str | None = Header(default=None),
    market: str | None = Query(default="domestic"),
) -> dict[str, object]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    uid = str(getattr(user, "id"))
    st = _readiness_store(cfg).get(uid)
    return {
        "ok": True,
        "market": market,
        "state": st.__dict__,
        "loop": get_readiness_builder_loop_status(uid),
        "readiness": paper_readiness_to_dict(evaluate_paper_readiness(cfg)),
        "data_health": paper_readiness_data_health(cfg),
        "config": {
            "enabled": bool(getattr(cfg, "readiness_builder_enabled", False)),
            "interval_sec": int(getattr(cfg, "readiness_builder_interval_sec", 60)),
            "target_pnl_rows": int(getattr(cfg, "readiness_builder_target_pnl_rows", 10)),
            "target_audit_rows": int(getattr(cfg, "readiness_builder_target_audit_rows", 3)),
            "max_attempts": int(getattr(cfg, "readiness_builder_max_attempts", 30)),
            "auto_start_on_live_auto": bool(getattr(cfg, "readiness_builder_auto_start_on_live_auto", True)),
        },
    }


@router.post("/readiness-builder/start")
def readiness_builder_start(
    authorization: str | None = Header(default=None),
    market: str | None = Query(default="domestic"),
) -> dict[str, object]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    uid = str(getattr(user, "id"))
    from .broker_routes import get_broker_service

    out = start_readiness_builder(cfg=cfg, broker_service=get_broker_service(), user_id=uid, market=market)
    return dict(out)


@router.post("/readiness-builder/stop")
def readiness_builder_stop(authorization: str | None = Header(default=None)) -> dict[str, object]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    uid = str(getattr(user, "id"))
    out = stop_readiness_builder(cfg=cfg, user_id=uid)
    return dict(out)


@router.post("/readiness-builder/tick")
def readiness_builder_tick(
    authorization: str | None = Header(default=None),
    market: str | None = Query(default="domestic"),
) -> dict[str, object]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    uid = str(getattr(user, "id"))
    from .broker_routes import get_broker_service

    out = tick_readiness_builder_once(cfg=cfg, broker_service=get_broker_service(), user_id=uid, market=market)
    return dict(out)


def runtime_safety_validation_for_user_id(cfg: BackendSettings, user_id: str) -> dict[str, object]:
    st = _store(cfg).get(user_id)
    has_operator_intent = bool(getattr(st, "history", None)) and len(list(getattr(st, "history") or [])) > 0
    requested_live = st.live_trading_flag if has_operator_intent else bool(cfg.live_trading)
    requested_confirm = st.secondary_confirm_flag if has_operator_intent else bool(cfg.live_trading_confirm)
    requested_extra = st.extra_approval_flag if has_operator_intent else bool(cfg.live_trading_extra_confirm)
    effective_live_flag = bool(st.live_trading_flag or requested_live)
    effective_confirm_flag = bool(st.secondary_confirm_flag or requested_confirm)
    effective_extra_flag = bool(st.extra_approval_flag or requested_extra)
    blockers: list[str] = []
    blocker_details: list[dict[str, str]] = []

    def _add(code: str, message: str) -> None:
        blocker_details.append({"code": code, "message": message})
        blockers.append(message)

    if cfg.trading_mode != "live":
        _add("TRADING_MODE_NOT_LIVE", "TRADING_MODE is not live")
    if not cfg.live_trading:
        _add("ENV_LIVE_TRADING_OFF", "ENV LIVE_TRADING is not true")
    if not cfg.live_trading_confirm:
        _add("ENV_LIVE_TRADING_CONFIRM_OFF", "ENV LIVE_TRADING_CONFIRM is not true")
    if not cfg.live_trading_extra_confirm:
        _add("ENV_LIVE_TRADING_EXTRA_CONFIRM_OFF", "ENV LIVE_TRADING_EXTRA_CONFIRM is not true")
    if not effective_live_flag:
        _add("APP_LIVE_TRADING_FLAG_OFF", "APP live trading flag is not enabled")
    if not effective_confirm_flag:
        _add("APP_SECONDARY_CONFIRM_MISSING", "APP secondary confirmation is missing")
    if not effective_extra_flag:
        _add("APP_EXTRA_APPROVAL_MISSING", "APP extra approval is missing")
    if st.live_emergency_stop:
        _add("APP_EMERGENCY_STOP_ON", "APP emergency stop is enabled")

    ks = _kill_switch_payload()
    if bool(ks.get("loss_limit_exceeded")):
        _add("KILL_SWITCH_TRIGGERED", str(ks.get("message") or "loss limit exceeded"))

    pr = evaluate_paper_readiness(cfg)
    paper = paper_readiness_to_dict(pr)
    if not pr.ok and not pr.bypassed:
        _add("PAPER_READINESS_FAILED", "모의투자 자동 검증 미통과 — /api/live-trading/paper-readiness 참고")
    return {
        "ok": len(blockers) == 0,
        "blockers": blockers,
        "blocker_details": blocker_details,
        "paper_readiness": paper,
        "kill_switch": ks,
    }


@router.get("/runtime-safety-validation")
def runtime_safety_validation(authorization: str | None = Header(default=None)) -> dict[str, object]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    return runtime_safety_validation_for_user_id(cfg, getattr(user, "id"))


class EmergencyStopRequest(BaseModel):
    enabled: bool
    reason: str = Field(min_length=3, max_length=240)
    actor: str = Field(default="user", min_length=1, max_length=64)


@router.post("/emergency-stop")
def set_emergency_stop(
    payload: EmergencyStopRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    store = _store(cfg)
    st = store.get(getattr(user, "id"))
    st.live_emergency_stop = bool(payload.enabled)
    st.updated_at_utc = datetime.now(timezone.utc).isoformat()
    append_risk_event(
        cfg.risk_events_jsonl,
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "LIVE_EMERGENCY_STOP_UPDATED",
            "actor": getattr(user, "id"),
            "app_actor": payload.actor,
            "enabled": bool(payload.enabled),
            "reason": payload.reason,
        },
    )
    st.history.insert(
        0,
        LiveSafetyHistoryItem(
            ts=st.updated_at_utc,
            actor=str(payload.actor or getattr(user, "id")),
            action="live_emergency_stop_updated",
            reason=f"{payload.reason} | enabled={bool(payload.enabled)}",
        ),
    )
    st.history = st.history[:100]
    store.upsert(st)
    return {"ok": True, **_status_payload_for_user(cfg, st)}


@router.get("/kill-switch-status")
def kill_switch_status(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _ = _current_user(authorization)
    return _kill_switch_payload()

class LiveMarketModeBody(BaseModel):
    manual_market_mode: str = Field(default="auto", description="auto | aggressive | neutral | defensive", min_length=2, max_length=16)


@router.get("/market-mode")
def get_live_market_mode(
    authorization: str | None = Header(default=None),
    market: str | None = None,
) -> dict[str, object]:
    user = _current_user(authorization)
    cfg = get_backend_settings()
    slot = str(market or "domestic").strip().lower()
    slot = "us" if slot == "us" else "domestic"
    manual = _mode_store(cfg).get(getattr(user, "id"), market=slot)
    return {"ok": True, "market": slot, "manual_market_mode_override": manual, "allowed": ["auto", "aggressive", "neutral", "defensive"]}


@router.post("/market-mode")
def set_live_market_mode(
    body: LiveMarketModeBody,
    authorization: str | None = Header(default=None),
    market: str | None = None,
) -> dict[str, object]:
    user = _current_user(authorization)
    cfg = get_backend_settings()
    slot = str(market or "domestic").strip().lower()
    slot = "us" if slot == "us" else "domestic"
    manual = _mode_store(cfg).set(getattr(user, "id"), market=slot, manual_market_mode=str(body.manual_market_mode or "auto"))
    append_risk_event(
        cfg.risk_events_jsonl,
        {"ts_utc": datetime.now(timezone.utc).isoformat(), "event_type": "LIVE_MARKET_MODE_UPDATED", "actor": getattr(user, "id"), "market": slot, "manual_market_mode_override": manual},
    )
    return {"ok": True, "market": slot, "manual_market_mode_override": manual, "allowed": ["auto", "aggressive", "neutral", "defensive"]}


def _auto_store(cfg: BackendSettings) -> LiveAutoGuardedStateStore:
    return LiveAutoGuardedStateStore(cfg.live_auto_guarded_state_store_json)


def _supported_auto_strategies() -> list[str]:
    return ["final_betting_v1", "scalp_rsi_flag_hf_v1", "scalp_macd_rsi_3m_v1", "swing_relaxed_v2", "multi"]


def _pick_selected_strategy(cfg: BackendSettings, st: LiveAutoGuardedState) -> str:
    supported = set(_supported_auto_strategies())
    s1 = (st.selected_strategy or "").strip()
    if s1 in supported:
        return s1
    env = (cfg.live_auto_strategy or "").strip()
    if env in supported:
        return env
    return "final_betting_v1"


def _mode_for_strategy(st: LiveAutoGuardedState, strategy_id: str) -> LiveAutoMode:
    raw = (st.mode_by_strategy or {}).get(strategy_id)
    m = (str(raw) if raw is not None else "").strip().lower()
    if m in {"aggressive", "auto", "passive"}:
        return m  # type: ignore[return-value]
    return "auto"


class LiveAutoGuardedStartRequest(BaseModel):
    strategy_id: str = Field(min_length=3, max_length=80)
    mode: LiveAutoMode = "auto"
    actor: str = Field(default="user", min_length=1, max_length=64)
    reason: str = Field(default="start_auto_guarded", min_length=3, max_length=240)


class LiveAutoGuardedStopRequest(BaseModel):
    actor: str = Field(default="user", min_length=1, max_length=64)
    reason: str = Field(default="stop_auto_guarded", min_length=3, max_length=240)


class LiveAutoGuardedModeUpdateRequest(BaseModel):
    strategy_id: str = Field(min_length=3, max_length=80)
    mode: LiveAutoMode
    actor: str = Field(default="user", min_length=1, max_length=64)
    reason: str = Field(default="update_auto_mode", min_length=3, max_length=240)


@router.get("/auto-guarded/status")
def auto_guarded_status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    st = _auto_store(cfg).get(getattr(user, "id"))
    LiveAutoGuardedStateStore.ensure_daily_rollover(st)
    _auto_store(cfg).upsert(st)
    selected = _pick_selected_strategy(cfg, st)
    return {
        "ok": True,
        "enabled": bool(st.enabled),
        "selected_strategy": st.selected_strategy,
        "effective_selected_strategy": selected,
        "supported_strategies": _supported_auto_strategies(),
        "mode_by_strategy": dict(st.mode_by_strategy or {}),
        "mode_effective": _mode_for_strategy(st, selected),
        "last_tick_at_utc": st.last_tick_at_utc,
        "last_eval_at_utc": st.last_eval_at_utc,
        "last_eval_strategies": list(st.last_eval_strategies or []),
        "last_eval_candidates": list(st.last_eval_candidates or []),
        "submitted": st.submitted,
        "last_decision": st.last_decision,
        "last_reason": st.last_reason,
        "daily_buy_count": int(st.daily_buy_count),
        "daily_sell_count": int(st.daily_sell_count),
    }


@router.post("/auto-guarded/start")
def auto_guarded_start(payload: LiveAutoGuardedStartRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    sid = (payload.strategy_id or "").strip()
    if sid not in set(_supported_auto_strategies()):
        raise HTTPException(status_code=400, detail={"error": "unsupported_strategy_id", "strategy_id": sid})
    st_store = _auto_store(cfg)
    st = st_store.get(getattr(user, "id"))
    LiveAutoGuardedStateStore.ensure_daily_rollover(st)
    st.enabled = True
    st.selected_strategy = sid
    st.mode_by_strategy[sid] = payload.mode
    st_store.upsert(st)
    append_risk_event(
        cfg.risk_events_jsonl,
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "LIVE_AUTO_GUARDED_STARTED",
            "actor": getattr(user, "id"),
            "app_actor": payload.actor,
            "strategy_id": sid,
            "mode": payload.mode,
            "reason": payload.reason,
        },
    )
    return {"ok": True, "enabled": bool(st.enabled), "selected_strategy": st.selected_strategy, "mode": payload.mode}


@router.post("/auto-guarded/stop")
def auto_guarded_stop(payload: LiveAutoGuardedStopRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    st_store = _auto_store(cfg)
    st = st_store.get(getattr(user, "id"))
    LiveAutoGuardedStateStore.ensure_daily_rollover(st)
    st.enabled = False
    st_store.upsert(st)
    append_risk_event(
        cfg.risk_events_jsonl,
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "LIVE_AUTO_GUARDED_STOPPED",
            "actor": getattr(user, "id"),
            "app_actor": payload.actor,
            "strategy_id": st.selected_strategy,
            "reason": payload.reason,
        },
    )
    return {"ok": True, "enabled": bool(st.enabled)}


@router.post("/auto-guarded/mode")
def auto_guarded_update_mode(
    payload: LiveAutoGuardedModeUpdateRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    sid = (payload.strategy_id or "").strip()
    if sid not in set(_supported_auto_strategies()):
        raise HTTPException(status_code=400, detail={"error": "unsupported_strategy_id", "strategy_id": sid})
    st_store = _auto_store(cfg)
    st = st_store.get(getattr(user, "id"))
    LiveAutoGuardedStateStore.ensure_daily_rollover(st)
    st.mode_by_strategy[sid] = payload.mode
    st_store.upsert(st)
    append_risk_event(
        cfg.risk_events_jsonl,
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "LIVE_AUTO_GUARDED_MODE_UPDATED",
            "actor": getattr(user, "id"),
            "app_actor": payload.actor,
            "strategy_id": sid,
            "mode": payload.mode,
            "reason": payload.reason,
        },
    )
    return {"ok": True, "strategy_id": sid, "mode": payload.mode}


def _candidate_rows_from_shadow(strategy_id: str, out: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sid = str(strategy_id or "").strip()
    rows: list[dict[str, Any]] = []
    shadow = out.get("shadow") if isinstance(out.get("shadow"), dict) else {}
    rej_by_sym = shadow.get("rejection_reasons_by_symbol") if isinstance(shadow, dict) else {}
    if not isinstance(rej_by_sym, dict):
        rej_by_sym = {}

    def _rej_reason_to_key(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, dict):
            k = v.get("reason") or v.get("code") or v.get("blocked_reason")
            return str(k or "").strip()
        if isinstance(v, list) and v:
            return str(v[0]).strip()
        return str(v).strip()

    top_counts: dict[str, int] = {}
    for _, vv in rej_by_sym.items():
        k = _rej_reason_to_key(vv)
        if not k:
            continue
        top_counts[k] = top_counts.get(k, 0) + 1
    top_reasons = [{"reason": k, "count": int(v)} for k, v in sorted(top_counts.items(), key=lambda x: (-x[1], x[0]))[:3]]

    meta: dict[str, Any] = {
        "strategy_id": sid,
        "asof_utc": out.get("asof_utc"),
        "ok": bool(out.get("ok")),
        "inspected_symbols": sorted([str(s).strip() for s in rej_by_sym.keys() if str(s).strip()]),
        "rejected_count": int(len(rej_by_sym)),
        "top_rejection_reasons": top_reasons,
    }
    if sid == "final_betting_v1":
        for c in list(out.get("candidates") or []):
            if not isinstance(c, dict):
                continue
            rows.append(
                {
                    "status": "candidate",
                    "strategy_id": sid,
                    "symbol": str(c.get("symbol") or ""),
                    "side": str(c.get("side") or ""),
                    "quantity": int(c.get("quantity") or 0),
                    "price": c.get("price"),
                    "score": c.get("score"),
                    "reason": str(c.get("rationale") or ""),
                    "order_id": None,
                    "ts_utc": out.get("asof_utc"),
                }
            )
        return rows, meta

    for o in list(out.get("generated_orders") or []):
        if not isinstance(o, dict):
            continue
        px = o.get("price")
        q = int(o.get("quantity") or 0)
        rows.append(
            {
                "status": "candidate",
                "strategy_id": sid,
                "symbol": str(o.get("symbol") or ""),
                "side": str(o.get("side") or ""),
                "quantity": q,
                "price": px,
                "score": None,
                "reason": str(o.get("signal_reason") or ""),
                "order_id": None,
                "ts_utc": out.get("asof_utc"),
            }
        )
    return rows, meta


def _submit_orders_if_allowed(
    *,
    broker_service: BrokerSecretService,
    cfg: BackendSettings,
    user_id: str,
    candidates: list[dict[str, Any]],
    mode: LiveAutoMode,
    safety_ok: bool,
    enabled: bool,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], str, str]:
    if not enabled:
        return candidates, {"buys": [], "sells": []}, "stopped", "enabled=false"
    if not safety_ok:
        return candidates, {"buys": [], "sells": []}, "blocked", "runtime_safety_not_ok"
    if mode == "passive":
        return candidates, {"buys": [], "sells": []}, "passive", "mode=passive"

    app_key, app_secret, account_no, product_code, tmode = broker_service.get_plain_credentials(user_id)
    if (tmode or "").strip().lower() != "live":
        return candidates, {"buys": [], "sells": []}, "blocked", "broker_account_not_live"
    tok = broker_service.ensure_cached_token_for_paper_start(user_id)
    if not tok.ok or not tok.access_token:
        return candidates, {"buys": [], "sells": []}, "blocked", str(tok.failure_code or "token_not_ready")

    api_base = broker_service._resolve_kis_api_base(tmode)  # type: ignore[attr-defined]
    client = build_kis_client_for_live_user(
        base_url=api_base,
        access_token=tok.access_token,
        app_key=app_key,
        app_secret=app_secret,
        live_execution_unlocked=True,
    )
    from app.brokers.live_broker import LiveBroker
    from app.orders.models import OrderRequest

    broker = LiveBroker(kis_client=client, account_no=account_no, account_product_code=product_code, logger=None)
    open_orders = broker.get_open_orders()
    positions = broker.get_positions()
    held = {str(getattr(p, "symbol", "") or "") for p in positions if int(getattr(p, "quantity", 0) or 0) > 0}

    submitted: dict[str, list[dict[str, Any]]] = {"buys": [], "sells": []}
    max_orders = 2 if mode == "aggressive" else 1
    submitted_count = 0
    out_rows: list[dict[str, Any]] = []
    for row in candidates:
        if submitted_count >= max_orders:
            out_rows.append({**row, "status": "skipped", "reason": "max_orders_per_tick"})
            continue
        sym = str(row.get("symbol") or "")
        side = str(row.get("side") or "")
        q = int(row.get("quantity") or 0)
        px = row.get("price")
        if not sym or side not in {"buy", "sell"} or q <= 0:
            out_rows.append({**row, "status": "rejected", "reason": "invalid_candidate"})
            continue
        if side == "buy":
            if sym in held:
                out_rows.append({**row, "status": "rejected", "reason": "already_holding"})
                continue
            dup = False
            for oo in open_orders:
                if str(getattr(oo, "symbol", "") or "") == sym and str(getattr(oo, "side", "") or "") == "buy":
                    if int(getattr(oo, "remaining_quantity", 0) or 0) > 0:
                        dup = True
                        break
            if dup:
                out_rows.append({**row, "status": "rejected", "reason": "duplicate_open_buy"})
                continue
            if px is None and mode != "aggressive":
                out_rows.append({**row, "status": "rejected", "reason": "price_missing_market_order_blocked"})
                continue

        order = OrderRequest(
            symbol=sym,
            side=side,  # type: ignore[arg-type]
            quantity=q,
            price=None if px is None else float(px),
            strategy_id=str(row.get("strategy_id") or ""),
            signal_reason=str(row.get("reason") or ""),
        )
        try:
            res = broker.place_order(order)
            submitted_count += 1
            entry = {"symbol": sym, "side": side, "quantity": q, "order_id": res.order_id, "accepted": bool(res.accepted)}
            submitted["buys" if side == "buy" else "sells"].append(entry)
            out_rows.append({**row, "status": "submitted" if bool(res.accepted) else "rejected", "order_id": res.order_id})
        except Exception as exc:
            out_rows.append({**row, "status": "rejected", "reason": f"submit_error:{str(exc)[:200]}"})

    reason = f"submitted={submitted_count} mode={mode}"
    return out_rows, submitted, "ok", reason


@router.post("/auto-guarded/tick")
def auto_guarded_tick(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    uid = getattr(user, "id")
    st_store = _auto_store(cfg)
    st = st_store.get(uid)
    LiveAutoGuardedStateStore.ensure_daily_rollover(st)
    selected = _pick_selected_strategy(cfg, st)
    mode = _mode_for_strategy(st, selected)

    svc = get_broker_service()
    safety = runtime_safety_validation_for_user_id(cfg, uid)
    safety_ok = bool(safety.get("ok"))

    strategies = ["final_betting_v1", "scalp_rsi_flag_hf_v1", "scalp_macd_rsi_3m_v1", "swing_relaxed_v2"] if selected == "multi" else [selected]
    candidates: list[dict[str, Any]] = []
    meta_by_strategy: dict[str, Any] = {}
    for sid in strategies:
        if sid == "final_betting_v1":
            out = generate_final_betting_shadow_candidates(broker_service=svc, backend_settings=cfg, user_id=uid, limit=10)
        elif sid == "swing_relaxed_v2":
            out = generate_swing_shadow_report(broker_service=svc, backend_settings=cfg, user_id=uid, strategy_id=sid)
        else:
            out = generate_intraday_shadow_report(broker_service=svc, backend_settings=cfg, user_id=uid, strategy_id=sid)
        rows, meta = _candidate_rows_from_shadow(sid, out)
        meta_by_strategy[sid] = meta
        candidates.extend(rows)

    out_rows, submitted, decision, reason = _submit_orders_if_allowed(
        broker_service=svc,
        cfg=cfg,
        user_id=uid,
        candidates=candidates,
        mode=mode,
        safety_ok=safety_ok,
        enabled=bool(st.enabled),
    )

    st.last_tick_at_utc = datetime.now(timezone.utc).isoformat()
    st.last_eval_at_utc = st.last_tick_at_utc
    st.last_eval_strategies = list(strategies)
    st.last_eval_candidates = list(out_rows)
    st.submitted = submitted
    st.last_decision = str(decision)
    st.last_reason = str(reason)
    for x in list(submitted.get("buys") or []):
        if bool(x.get("accepted")):
            st.daily_buy_count += 1
    for x in list(submitted.get("sells") or []):
        if bool(x.get("accepted")):
            st.daily_sell_count += 1
    st_store.upsert(st)

    return {
        "ok": True,
        "enabled": bool(st.enabled),
        "selected_strategy": st.selected_strategy,
        "effective_selected_strategy": selected,
        "mode_effective": mode,
        "last_eval_strategies": list(st.last_eval_strategies),
        "last_eval_candidates": list(st.last_eval_candidates),
        "submitted": st.submitted,
        "daily_buy_count": int(st.daily_buy_count),
        "daily_sell_count": int(st.daily_sell_count),
        "meta_by_strategy": meta_by_strategy,
        "safety": safety,
    }


@router.get("/compact-dashboard")
def compact_dashboard(
    authorization: str | None = Header(default=None),
    include_raw: bool = Query(default=False),
) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    uid = getattr(user, "id")
    safety_state = _store(cfg).get(uid)
    live_status_payload = _status_payload_for_user(cfg, safety_state)
    safety = runtime_safety_validation_for_user_id(cfg, uid)

    auto_state = _auto_store(cfg).get(uid)
    LiveAutoGuardedStateStore.ensure_daily_rollover(auto_state)
    _auto_store(cfg).upsert(auto_state)
    selected = _pick_selected_strategy(cfg, auto_state)
    market_closed_notice = ""
    try:
        now = kst_now().time()
        if not (parse_krx_hhmm("090000") <= now <= parse_krx_hhmm("152000")):
            market_closed_notice = "장 종료로 신규 후보 평가 제한"
    except Exception:
        market_closed_notice = ""

    svc = get_broker_service()
    app_key, app_secret, account_no, product_code, tmode = svc.get_plain_credentials(uid)
    positions: list[dict[str, Any]] = []
    open_orders: list[dict[str, Any]] = []
    recent_fills: list[dict[str, Any]] = []
    account_ok = False
    account_err = ""
    try:
        if (tmode or "").strip().lower() == "live":
            tok = svc.ensure_cached_token_for_paper_start(uid)
            if tok.ok and tok.access_token:
                api_base = svc._resolve_kis_api_base(tmode)  # type: ignore[attr-defined]
                client = build_kis_client_for_live_user(
                    base_url=api_base,
                    access_token=tok.access_token,
                    app_key=app_key,
                    app_secret=app_secret,
                    live_execution_unlocked=False,
                )
                from app.brokers.live_broker import LiveBroker

                broker = LiveBroker(kis_client=client, account_no=account_no, account_product_code=product_code, logger=None)
                for p in broker.get_positions():
                    positions.append(
                        {
                            "symbol": str(getattr(p, "symbol", "") or ""),
                            "quantity": int(getattr(p, "quantity", 0) or 0),
                            "average_price": float(getattr(p, "average_price", 0.0) or 0.0),
                            "current_price": None,
                            "market_value": None,
                            "pnl_pct": None,
                        }
                    )
                for o in broker.get_open_orders():
                    open_orders.append(
                        {
                            "order_id": str(getattr(o, "order_id", "") or ""),
                            "symbol": str(getattr(o, "symbol", "") or ""),
                            "side": str(getattr(o, "side", "") or ""),
                            "remaining_quantity": int(getattr(o, "remaining_quantity", 0) or 0),
                            "price": float(getattr(o, "price", 0.0) or 0.0) if getattr(o, "price", None) is not None else None,
                            "created_at_utc": getattr(o, "created_at", datetime.now(timezone.utc)).isoformat(),
                        }
                    )
                for f in broker.get_fills()[-50:]:
                    recent_fills.append(
                        {
                            "symbol": str(getattr(f, "symbol", "") or ""),
                            "side": str(getattr(f, "side", "") or ""),
                            "quantity": int(getattr(f, "quantity", 0) or 0),
                            "order_id": str(getattr(f, "order_id", "") or ""),
                            "price": float(getattr(f, "fill_price", 0.0) or 0.0),
                            "filled_at_utc": getattr(f, "filled_at", datetime.now(timezone.utc)).isoformat(),
                        }
                    )
                account_ok = True
            else:
                account_err = str(tok.failure_code or "token_not_ready")
        else:
            account_err = "broker_account_not_live"
    except Exception as exc:
        account_err = str(exc)

    payload: dict[str, Any] = {
        "live": {
            "can_place_live_order": bool(live_status_payload.get("can_place_live_order")),
            "blockers": list(safety.get("blockers") or []),
            "bypass": bool(cfg.live_unlock_bypass),
            "emergency_stop": bool(getattr(safety_state, "live_emergency_stop", False)),
            "warning_message": str(live_status_payload.get("warning_message") or ""),
            "live_trading_flag": bool(live_status_payload.get("live_trading_flag")),
            "secondary_confirm_flag": bool(live_status_payload.get("secondary_confirm_flag")),
            "extra_approval_flag": bool(live_status_payload.get("extra_approval_flag")),
            "effective_live_trading_flag": bool(live_status_payload.get("effective_live_trading_flag")),
            "effective_secondary_confirm_flag": bool(live_status_payload.get("effective_secondary_confirm_flag")),
            "effective_extra_approval_flag": bool(live_status_payload.get("effective_extra_approval_flag")),
        },
        "auto": {
            "enabled": bool(auto_state.enabled),
            "can_place_auto_order": bool(safety.get("ok")) and bool(auto_state.enabled),
            "selected_strategy": selected,
            "mode": _mode_for_strategy(auto_state, selected),
            "last_tick_at_utc": auto_state.last_tick_at_utc,
            "last_eval_at_utc": auto_state.last_eval_at_utc,
            "last_decision": auto_state.last_decision,
            "last_reason": auto_state.last_reason,
            "daily_buy_count": int(auto_state.daily_buy_count),
            "daily_sell_count": int(auto_state.daily_sell_count),
            "last_eval_candidates": list(auto_state.last_eval_candidates or []),
            "submitted": auto_state.submitted,
            "market_notice": market_closed_notice,
        },
        "strategies": {sid: {"shadow_candidates": [], "auto_candidates": [], "summary": {}} for sid in _supported_auto_strategies() if sid != "multi"},
        "account": {
            "ok": bool(account_ok),
            "error": account_err,
            "positions": positions,
            "open_orders": open_orders,
            "recent_fills": recent_fills,
        },
    }

    try:
        by_id: dict[str, Any] = {}
        summ = auto_state.last_eval_summary if isinstance(auto_state.last_eval_summary, dict) else {}
        for row in list(summ.get("strategies") or []) if isinstance(summ, dict) else []:
            if not isinstance(row, dict):
                continue
            sid = str(row.get("strategy_id") or "").strip()
            if sid:
                by_id[sid] = row

        to_fill = ["final_betting_v1", "scalp_rsi_flag_hf_v1", "scalp_macd_rsi_3m_v1", "swing_relaxed_v2"] if selected == "multi" else [selected]
        for sid in to_fill:
            if sid not in payload["strategies"]:
                continue
            payload["strategies"][sid]["auto_candidates"] = [c for c in list(auto_state.last_eval_candidates or []) if isinstance(c, dict) and str(c.get("strategy_id") or "") == sid]
            payload["strategies"][sid]["summary"] = dict(by_id.get(sid) or {})
            try:
                if sid == "final_betting_v1":
                    out = generate_final_betting_shadow_candidates(broker_service=svc, backend_settings=cfg, user_id=uid, limit=10)
                elif sid == "swing_relaxed_v2":
                    out = generate_swing_shadow_report(broker_service=svc, backend_settings=cfg, user_id=uid, strategy_id=sid)
                else:
                    out = generate_intraday_shadow_report(broker_service=svc, backend_settings=cfg, user_id=uid, strategy_id=sid)
                rows, meta = _candidate_rows_from_shadow(sid, out if isinstance(out, dict) else {})
                payload["strategies"][sid]["shadow_candidates"] = rows
                if not payload["strategies"][sid]["summary"]:
                    payload["strategies"][sid]["summary"] = meta
            except Exception as exc:
                if not payload["strategies"][sid]["summary"]:
                    payload["strategies"][sid]["summary"] = {"strategy_id": sid, "ok": False, "error": str(exc)[:200]}
    except Exception:
        pass

    if include_raw:
        payload["raw"] = {
            "live_status": live_status_payload,
            "runtime_safety": safety,
            "auto_state": auto_state.__dict__,
        }
    return payload
