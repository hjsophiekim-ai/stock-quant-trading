from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.risk.rules import RiskRules, RiskSnapshot

KillState = Literal["RUNNING", "COOLDOWN", "HALTED_DAILY", "SYSTEM_OFF"]


@dataclass
class KillSwitch:
    rules: RiskRules
    state: KillState = "RUNNING"
    last_reason: str = "No halt condition"

    @property
    def is_halted(self) -> bool:
        return self.state != "RUNNING"

    def evaluate(self, snapshot: RiskSnapshot) -> bool:
        decision = self.rules.evaluate_global_guard(snapshot)
        if decision.approved:
            self.state = "RUNNING"
            self.last_reason = decision.reason
            return False

        if decision.reason_code == "SYSTEM_OFF_TOTAL_LOSS":
            self.state = "SYSTEM_OFF"
        elif decision.reason_code in {"TRADING_COOLDOWN_ACTIVE", "HALT_ROLLING_LOSS_LIMIT"}:
            self.state = "COOLDOWN"
        else:
            self.state = "HALTED_DAILY"
        self.last_reason = decision.reason
        return True

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
