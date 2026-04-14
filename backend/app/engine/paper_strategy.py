"""Paper 세션에서 사용하는 전략 ID → 인스턴스 매핑 (모의 전용)."""

from __future__ import annotations

from app.strategy.base_strategy import BaseStrategy
from app.strategy.bear_strategy import BearStrategy
from app.strategy.bull_strategy import BullStrategy
from app.strategy.swing_relaxed_strategy import SwingRelaxedStrategy
from app.strategy.swing_relaxed_v2_strategy import SwingRelaxedV2Strategy
from app.strategy.swing_strategy import SwingStrategy
from app.strategy.scalp_momentum_v1_strategy import ScalpMomentumV1Strategy
from app.strategy.scalp_momentum_v2_strategy import ScalpMomentumV2Strategy


def strategy_for_paper_id(strategy_id: str) -> BaseStrategy:
    sid = (strategy_id or "").lower().strip()
    if sid == "bull_focus_v1":
        return BullStrategy()
    if sid == "defensive_v1":
        return BearStrategy()
    if sid == "swing_relaxed_v1":
        return SwingRelaxedStrategy()
    if sid == "swing_relaxed_v2":
        return SwingRelaxedV2Strategy()
    if sid == "scalp_momentum_v1":
        return ScalpMomentumV1Strategy()
    if sid == "scalp_momentum_v2":
        return ScalpMomentumV2Strategy()
    return SwingStrategy()
