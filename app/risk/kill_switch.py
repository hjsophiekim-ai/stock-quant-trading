from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal

from app.risk.reason_codes import RiskReasonCode
from app.risk.rules import RiskRules, RiskSnapshot

KillState = Literal["RUNNING", "COOLDOWN", "HALTED_DAILY", "SYSTEM_OFF"]

RiskEventCallback = Callable[[dict[str, Any]], None]


@dataclass
class KillSwitch:
    rules: RiskRules
    state: KillState = "RUNNING"
    last_reason: str = "No halt condition"
    last_reason_code: str = ""
    new_entries_blocked: bool = False
    system_risk_off: bool = False
    _on_event: RiskEventCallback | None = field(default=None, repr=False)

    def set_event_sink(self, sink: RiskEventCallback | None) -> None:
        self._on_event = sink

    def _emit(self, payload: dict[str, Any]) -> None:
        if self._on_event is not None:
            self._on_event(payload)

    @property
    def is_halted(self) -> bool:
        """레거시: 전체 루프 중단이 필요한 경우(SYSTEM_OFF)만 True 권장."""
        return self.system_risk_off

    @property
    def should_abort_trading_cycle(self) -> bool:
        """총 손실 한도 등으로 자동매매 사이클 자체를 멈출지."""
        return self.system_risk_off

    def evaluate(self, snapshot: RiskSnapshot) -> bool:
        """
        True  → 스케줄러가 **전체** 일일 사이클을 건너뜀 (현재는 총손실 risk_off 만).
        False → 사이클 진행; 신규 매수는 approve_order / new_entries_blocked 로 별도 차단.
        """
        decision = self.rules.evaluate_global_guard(snapshot)
        self.last_reason_code = decision.reason_code
        if decision.approved:
            self.state = "RUNNING"
            self.last_reason = decision.reason
            self.new_entries_blocked = False
            self.system_risk_off = False
            return False

        if decision.reason_code == RiskReasonCode.SYSTEM_OFF_TOTAL_LOSS.value:
            self.state = "SYSTEM_OFF"
            self.system_risk_off = True
            self.new_entries_blocked = True
            self.last_reason = decision.reason
            self._emit(
                {
                    "type": "risk_off",
                    "reason_code": decision.reason_code,
                    "reason": decision.reason,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
            return True

        self.system_risk_off = False
        if decision.reason_code == RiskReasonCode.HALT_DAILY_LOSS.value:
            self.state = "HALTED_DAILY"
            self.new_entries_blocked = True
            self.last_reason = decision.reason
            self._emit(
                {
                    "type": "daily_loss_halt_entries",
                    "reason_code": decision.reason_code,
                    "reason": decision.reason,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
            return False

        if decision.reason_code in {
            RiskReasonCode.TRADING_COOLDOWN_ACTIVE.value,
            RiskReasonCode.HALT_ROLLING_LOSS_LIMIT.value,
        }:
            self.state = "COOLDOWN"
            self.new_entries_blocked = True
            self.last_reason = decision.reason
            self._emit(
                {
                    "type": "cooldown_entries",
                    "reason_code": decision.reason_code,
                    "reason": decision.reason,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
            return False

        self.state = "HALTED_DAILY"
        self.new_entries_blocked = True
        self.last_reason = decision.reason
        return False

    def recommend_cooldown_until(self, snapshot: RiskSnapshot) -> datetime | None:
        """
        Returns a cooldown-until timestamp when adaptive drawdown controls suggest
        pausing new entries after repeated losses.
        """
        adaptive = self.rules.adaptive_guard(snapshot)
        if adaptive.cooldown_required or adaptive.loss_streak_triggered:
            return datetime.now(timezone.utc) + timedelta(minutes=self.rules.limits.adaptive_trading_cooldown_minutes)
        if adaptive.performance_deteriorating:
            return datetime.now(timezone.utc) + timedelta(minutes=self.rules.limits.adaptive_trading_cooldown_minutes)
        return None
