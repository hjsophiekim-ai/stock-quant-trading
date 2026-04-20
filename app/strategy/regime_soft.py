"""
5단계 시장 국면(soft) + 점수·사이즈 배수 — 레거시 `MarketRegime` 4분류와 병행.

레거지 `classify_market_regime` 결과는 유지하고, 진입 허용·비중 조절에만 soft 레이어를 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.strategy.market_regime import MarketRegime, MarketRegimeFeatures

SoftMarketRegime = Literal["bullish", "mild_bullish", "neutral", "mild_bearish", "bearish"]


@dataclass(frozen=True)
class SoftRegimeResult:
    market_regime: SoftMarketRegime
    regime_score: float
    regime_entry_allowed: bool
    regime_size_multiplier: float
    regime_block_reason: str | None


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_soft_regime(
    features: MarketRegimeFeatures,
    legacy_regime: MarketRegime,
    *,
    high_vol_override_block: bool = True,
) -> SoftRegimeResult:
    """
    - regime_score: 대략 [-1, 1] (높을수록 순조)
    - high_volatility_risk: 레거시와 동일하게 신규 진입 제한(override 시 완화 가능)
    """
    if legacy_regime == "high_volatility_risk" and high_vol_override_block:
        return SoftRegimeResult(
            market_regime="bearish",
            regime_score=-0.9,
            regime_entry_allowed=False,
            regime_size_multiplier=0.0,
            regime_block_reason="high_volatility_risk",
        )

    kr = (features.kospi_return_pct + features.sp500_return_pct) / 2.0
    k_slope = (
        features.kospi_ma20_slope_pct + features.kospi_ma60_slope_pct + features.kospi_ma120_slope_pct
    ) / 3.0
    u_slope = (
        features.sp500_ma20_slope_pct + features.sp500_ma60_slope_pct + features.sp500_ma120_slope_pct
    ) / 3.0
    slope_avg = (k_slope + u_slope) / 2.0

    vol_pen = 0.0
    if features.volatility_level >= 22.0:
        vol_pen = _clip((features.volatility_level - 22.0) / 18.0, 0.0, 0.35)
    if features.volatility_change_pct > 1.5:
        vol_pen = max(vol_pen, _clip((features.volatility_change_pct - 1.5) / 6.0, 0.0, 0.2))

    raw = 0.45 * _clip(kr / 4.0, -1.0, 1.0) + 0.35 * _clip(slope_avg / 0.45, -1.0, 1.0) + 0.2 * _clip(
        (features.kospi_return_pct - features.sp500_return_pct) / 3.0, -1.0, 1.0
    )
    score = _clip(raw - vol_pen, -1.0, 1.0)

    if score >= 0.55:
        label: SoftMarketRegime = "bullish"
        mult = 1.0
        allowed = True
        br = None
    elif score >= 0.2:
        label = "mild_bullish"
        mult = 0.9
        allowed = True
        br = None
    elif score >= -0.2:
        label = "neutral"
        mult = 0.75
        allowed = True
        br = None
    elif score >= -0.55:
        label = "mild_bearish"
        mult = 0.55
        allowed = True
        br = None
    else:
        label = "bearish"
        mult = 0.3
        allowed = True
        br = "soft_bearish_size_only" if score < -0.75 else None

    if legacy_regime == "bearish_trend" and label in ("neutral", "mild_bearish", "bearish"):
        mult *= 0.85
    if legacy_regime == "bullish_trend" and label in ("bullish", "mild_bullish"):
        mult = min(1.0, mult * 1.05)

    return SoftRegimeResult(
        market_regime=label,
        regime_score=round(score, 4),
        regime_entry_allowed=bool(allowed),
        regime_size_multiplier=round(_clip(mult, 0.15, 1.0), 4),
        regime_block_reason=br,
    )
