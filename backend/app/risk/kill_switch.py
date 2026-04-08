"""KillSwitch 는 `app.risk.kill_switch` 단일 구현. 이벤트는 `append_risk_event` 로 기록."""

from __future__ import annotations

from app.risk.kill_switch import KillSwitch, KillState
from app.risk.rules import RiskRules, RiskSnapshot
from backend.app.core.config import get_backend_settings
from backend.app.risk.audit import append_risk_event


def attach_kill_switch_event_logging(ks: KillSwitch) -> None:
    """스케줄러 등에서 생성한 KillSwitch 에 JSONL 이벤트 싱크 연결."""

    def _sink(ev: dict) -> None:
        append_risk_event(get_backend_settings().risk_events_jsonl, ev)

    ks.set_event_sink(_sink)


def evaluate_kill_switch_with_logging(ks: KillSwitch, snapshot: RiskSnapshot) -> bool:
    return ks.evaluate(snapshot)
