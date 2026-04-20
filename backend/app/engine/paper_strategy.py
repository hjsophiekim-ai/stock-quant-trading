"""Paper 세션에서 사용하는 전략 ID → 인스턴스 매핑 (모의 전용)."""

from __future__ import annotations

from app.config import get_settings
from app.strategy.base_strategy import BaseStrategy
from app.strategy.bear_strategy import BearStrategy
from app.strategy.bull_strategy import BullStrategy
from app.strategy.final_betting_v1_strategy import FinalBettingV1Strategy
from app.strategy.swing_relaxed_strategy import SwingRelaxedStrategy
from app.strategy.swing_relaxed_v2_strategy import SwingRelaxedV2Strategy
from app.strategy.swing_strategy import SwingStrategy, SwingStrategyConfig
from app.strategy.scalp_momentum_v1_strategy import ScalpMomentumV1Strategy
from app.strategy.scalp_momentum_v2_strategy import ScalpMomentumV2Strategy
from app.strategy.scalp_momentum_v3_strategy import ScalpMomentumV3Strategy
from app.strategy.scalp_macd_rsi_3m_v1_strategy import ScalpMacdRsi3mV1Strategy
from app.strategy.scalp_rsi_flag_hf_v1_strategy import ScalpRsiFlagHfV1Strategy
from app.strategy.us_scalp_momentum_v1_strategy import UsScalpMomentumV1Strategy
from app.strategy.us_swing_relaxed_v1_strategy import UsSwingRelaxedV1Strategy


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
    if sid == "scalp_momentum_v3":
        return ScalpMomentumV3Strategy()
    if sid == "scalp_macd_rsi_3m_v1":
        return ScalpMacdRsi3mV1Strategy()
    if sid in ("scalp_rsi_flag_hf_v1", "intraday_rsi_flag_hf_v1"):
        inst = ScalpRsiFlagHfV1Strategy()
        setattr(inst, "_paper_strategy_id", sid)
        return inst
    if sid == "final_betting_v1":
        return FinalBettingV1Strategy()
    if sid == "us_swing_relaxed_v1":
        return UsSwingRelaxedV1Strategy()
    if sid == "us_scalp_momentum_v1":
        return UsScalpMomentumV1Strategy()
    cfg = get_settings()
    top_n = max(3, int(getattr(cfg, "paper_ranking_top_n_default", 5)))
    return SwingStrategy(config=SwingStrategyConfig(ranking_top_n=top_n))
