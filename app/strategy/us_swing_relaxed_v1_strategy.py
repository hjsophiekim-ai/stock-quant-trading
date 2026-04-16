"""미국 Paper 스윙 — 국내 `SwingRelaxedStrategy` 신호·리스크 경로 재사용(유니버스는 US 전용 빌더에서 공급)."""

from __future__ import annotations

from dataclasses import dataclass

from app.strategy.swing_relaxed_strategy import SwingRelaxedStrategy


@dataclass
class UsSwingRelaxedV1Strategy(SwingRelaxedStrategy):
    """strategy_id=us_swing_relaxed_v1 — 주문·로그 구분용."""

