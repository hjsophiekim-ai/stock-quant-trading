"""Paper 세션에서 사용하는 전략 ID → 인스턴스 매핑 (모의 전용)."""

from __future__ import annotations

from app.strategy.base_strategy import BaseStrategy
from app.strategy.bear_strategy import BearStrategy
from app.strategy.bull_strategy import BullStrategy
from app.strategy.swing_strategy import SwingStrategy


def strategy_for_paper_id(strategy_id: str) -> BaseStrategy:
    sid = (strategy_id or "").lower().strip()
    if sid == "bull_focus_v1":
        return BullStrategy()
    if sid == "defensive_v1":
        return BearStrategy()
    return SwingStrategy()
