"""미국 Paper 단타 — `ScalpMomentumV1Strategy` 파이프라인 재사용(세션·분봉은 US 경로에서 주입)."""

from __future__ import annotations

from dataclasses import dataclass

from app.strategy.scalp_momentum_v1_strategy import ScalpMomentumV1Strategy


@dataclass
class UsScalpMomentumV1Strategy(ScalpMomentumV1Strategy):
    """strategy_id=us_scalp_momentum_v1."""

