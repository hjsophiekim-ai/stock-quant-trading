from dataclasses import dataclass
from typing import Literal

from app.risk.rules import RiskRules, RiskSnapshot

KillState = Literal["RUNNING", "HALTED_DAILY", "SYSTEM_OFF"]


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
        else:
            self.state = "HALTED_DAILY"
        self.last_reason = decision.reason
        return True
