from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.risk.audit import append_risk_event
from backend.app.risk.live_unlock_gate import evaluate_paper_readiness, paper_readiness_to_dict

from ..core.config import get_backend_settings

router = APIRouter(prefix="/live-trading", tags=["live-trading"])


class LiveSettingsUpdateRequest(BaseModel):
    live_trading_flag: bool
    secondary_confirm_flag: bool
    extra_approval_flag: bool
    reason: str = Field(min_length=3, max_length=240)
    actor: str = Field(default="user", min_length=1, max_length=64)


@dataclass
class HistoryItem:
    ts: str
    actor: str
    action: str
    reason: str


@dataclass
class LiveSafetyRuntime:
    live_trading_flag: bool = False
    secondary_confirm_flag: bool = False
    extra_approval_flag: bool = False
    settings_history: list[HistoryItem] = field(default_factory=list)
    # Mock metrics for UI and API contract. TODO: wire real risk snapshot.
    daily_loss_pct: float = -1.4
    total_loss_pct: float = -4.7

    def update(self, req: LiveSettingsUpdateRequest) -> None:
        self.live_trading_flag = req.live_trading_flag
        self.secondary_confirm_flag = req.secondary_confirm_flag
        self.extra_approval_flag = req.extra_approval_flag
        self.settings_history.insert(
            0,
            HistoryItem(
                ts=datetime.now(timezone.utc).isoformat(),
                actor=req.actor,
                action="update_live_safety_settings",
                reason=req.reason,
            ),
        )
        self.settings_history = self.settings_history[:100]


runtime = LiveSafetyRuntime()


def _status_payload() -> dict[str, object]:
    cfg = get_backend_settings()
    readiness = evaluate_paper_readiness(cfg)
    paper_ok = readiness.ok or readiness.bypassed
    can_place = (
        cfg.trading_mode == "live"
        and runtime.live_trading_flag
        and runtime.secondary_confirm_flag
        and runtime.extra_approval_flag
        and cfg.live_trading
        and cfg.live_trading_confirm
        and cfg.live_trading_extra_confirm
        and paper_ok
    )
    if not can_place:
        if not (
            cfg.trading_mode == "live"
            and runtime.live_trading_flag
            and runtime.secondary_confirm_flag
            and runtime.extra_approval_flag
            and cfg.live_trading
            and cfg.live_trading_confirm
            and cfg.live_trading_extra_confirm
        ):
            warning = "LIVE 주문 잠금 상태: 다중 승인·환경 설정이 완료되지 않았습니다."
        elif not paper_ok:
            warning = readiness.user_message_ko
        else:
            warning = "LIVE 주문 잠금 상태"
    else:
        warning = "LIVE 주문 가능 상태 (모든 승인·모의 검증 완료)"
    return {
        "trading_mode": cfg.trading_mode,
        "live_trading_flag": runtime.live_trading_flag,
        "secondary_confirm_flag": runtime.secondary_confirm_flag,
        "extra_approval_flag": runtime.extra_approval_flag,
        "paper_readiness_ok": paper_ok,
        "can_place_live_order": can_place,
        "trading_badge": "live" if can_place else "test",
        "warning_message": warning,
    }


@router.get("/status")
def live_status() -> dict[str, object]:
    return _status_payload()


def _attempting_full_app_unlock(req: LiveSettingsUpdateRequest) -> bool:
    return bool(req.live_trading_flag and req.secondary_confirm_flag and req.extra_approval_flag)


@router.post("/settings")
def update_live_settings(payload: LiveSettingsUpdateRequest) -> dict[str, object]:
    cfg = get_backend_settings()
    if _attempting_full_app_unlock(payload):
        pr = evaluate_paper_readiness(cfg)
        if not pr.ok and not pr.bypassed:
            append_risk_event(
                cfg.risk_events_jsonl,
                {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "event_type": "LIVE_UNLOCK_DENIED",
                    "actor": payload.actor,
                    "reason": payload.reason,
                    "paper_readiness": pr.technical_summary,
                    "user_message_ko": pr.user_message_ko,
                },
            )
            runtime.settings_history.insert(
                0,
                HistoryItem(
                    ts=datetime.now(timezone.utc).isoformat(),
                    actor=payload.actor,
                    action="live_unlock_denied_paper_readiness",
                    reason=f"{payload.reason} | {pr.user_message_ko[:200]}",
                ),
            )
            runtime.settings_history = runtime.settings_history[:100]
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "live_unlock_blocked",
                    "message_ko": pr.user_message_ko,
                    "paper_readiness": paper_readiness_to_dict(pr),
                },
            )
        append_risk_event(
            cfg.risk_events_jsonl,
            {
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "event_type": "LIVE_UNLOCK_APPROVED_CHECKLIST",
                "actor": payload.actor,
                "reason": payload.reason,
                "paper_readiness": pr.technical_summary,
            },
        )
    runtime.update(payload)
    return {"ok": True, **_status_payload()}


@router.get("/settings-history")
def settings_history() -> dict[str, object]:
    return {"items": [item.__dict__ for item in runtime.settings_history]}


@router.get("/paper-readiness")
def paper_readiness() -> dict[str, object]:
    cfg = get_backend_settings()
    pr = evaluate_paper_readiness(cfg)
    return paper_readiness_to_dict(pr)


@router.get("/runtime-safety-validation")
def runtime_safety_validation() -> dict[str, object]:
    cfg = get_backend_settings()
    blockers: list[str] = []
    if cfg.trading_mode != "live":
        blockers.append("TRADING_MODE is not live")
    if not cfg.live_trading:
        blockers.append("ENV LIVE_TRADING is not true")
    if not cfg.live_trading_confirm:
        blockers.append("ENV LIVE_TRADING_CONFIRM is not true")
    if not cfg.live_trading_extra_confirm:
        blockers.append("ENV LIVE_TRADING_EXTRA_CONFIRM is not true")
    if not runtime.live_trading_flag:
        blockers.append("APP live trading flag is not enabled")
    if not runtime.secondary_confirm_flag:
        blockers.append("APP secondary confirmation is missing")
    if not runtime.extra_approval_flag:
        blockers.append("APP extra approval is missing")
    pr = evaluate_paper_readiness(cfg)
    paper = paper_readiness_to_dict(pr)
    if not pr.ok and not pr.bypassed:
        blockers.append("모의투자 자동 검증 미통과 — /api/live-trading/paper-readiness 참고")
    return {
        "ok": len(blockers) == 0,
        "blockers": blockers,
        "paper_readiness": paper,
    }


@router.get("/kill-switch-status")
def kill_switch_status() -> dict[str, object]:
    cfg = get_backend_settings()
    daily_exceeded = abs(runtime.daily_loss_pct) >= 3.0
    total_exceeded = abs(runtime.total_loss_pct) >= 10.0
    exceeded = daily_exceeded or total_exceeded
    state: Literal["NORMAL", "TRIGGERED", "COOLDOWN"] = "TRIGGERED" if exceeded else "NORMAL"
    return {
        "kill_switch_state": state,
        "daily_loss_pct": runtime.daily_loss_pct,
        "total_loss_pct": runtime.total_loss_pct,
        "daily_loss_limit_pct": 3.0,
        "total_loss_limit_pct": 10.0,
        "loss_limit_exceeded": exceeded,
        "message": "손실 제한 초과: LIVE 주문 차단" if exceeded else "정상 범위",
        # TODO: replace mock daily/total loss metrics with real risk engine snapshot.
    }
