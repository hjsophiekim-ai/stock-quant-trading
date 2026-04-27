from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

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
from ..services.live_safety_state_store import LiveSafetyHistoryItem, LiveSafetyState, LiveSafetyStateStore
from ..services.live_market_mode_store import LiveMarketModeStore

from .auth_routes import get_current_user_from_auth_header

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
    can_place = (
        cfg.trading_mode == "live"
        and st.live_trading_flag
        and st.secondary_confirm_flag
        and st.extra_approval_flag
        and (not st.live_emergency_stop)
        and cfg.live_trading
        and cfg.live_trading_confirm
        and cfg.live_trading_extra_confirm
        and paper_ok
        and (not bool(ks.get("loss_limit_exceeded")))
    )
    if not can_place:
        if not (
            cfg.trading_mode == "live"
            and st.live_trading_flag
            and st.secondary_confirm_flag
            and st.extra_approval_flag
            and cfg.live_trading
            and cfg.live_trading_confirm
            and cfg.live_trading_extra_confirm
        ):
            warning = "LIVE 주문 잠금 상태: 다중 승인·환경 설정이 완료되지 않았습니다."
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
        "env_live_trading": bool(cfg.live_trading),
        "env_live_trading_confirm": bool(cfg.live_trading_confirm),
        "env_live_trading_extra_confirm": bool(cfg.live_trading_extra_confirm),
        "operator_intent_has_history": bool(has_operator_intent),
        "live_trading_flag": st.live_trading_flag,
        "secondary_confirm_flag": st.secondary_confirm_flag,
        "extra_approval_flag": st.extra_approval_flag,
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
    if not st.live_trading_flag:
        _add("APP_LIVE_TRADING_FLAG_OFF", "APP live trading flag is not enabled")
    if not st.secondary_confirm_flag:
        _add("APP_SECONDARY_CONFIRM_MISSING", "APP secondary confirmation is missing")
    if not st.extra_approval_flag:
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
    manual_market_mode: str = Field(
        default="auto",
        description="auto | aggressive | neutral | defensive",
        min_length=2,
        max_length=16,
    )


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
    return {
        "ok": True,
        "market": slot,
        "manual_market_mode_override": manual,
        "allowed": ["auto", "aggressive", "neutral", "defensive"],
    }


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
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "LIVE_MARKET_MODE_UPDATED",
            "actor": getattr(user, "id"),
            "market": slot,
            "manual_market_mode_override": manual,
        },
    )
    return {
        "ok": True,
        "market": slot,
        "manual_market_mode_override": manual,
        "allowed": ["auto", "aggressive", "neutral", "defensive"],
    }
