from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from app.strategy.market_regime import (
    MarketRegimeConfig,
    MarketRegimeInputs,
    allowed_actions_for_regime,
    classify_market_regime,
)


def _series_df(values: list[float]) -> pd.DataFrame:
    base = datetime(2026, 1, 1)
    rows = [{"date": base + timedelta(days=i), "close": float(v)} for i, v in enumerate(values)]
    return pd.DataFrame(rows)


def _vol_df(values: list[float]) -> pd.DataFrame:
    base = datetime(2026, 1, 1)
    rows = [{"date": base + timedelta(days=i), "value": float(v)} for i, v in enumerate(values)]
    return pd.DataFrame(rows)


def test_classify_bullish_trend() -> None:
    kospi = _series_df([100 + i for i in range(30)])
    sp500 = _series_df([200 + i * 1.2 for i in range(30)])
    vol = _vol_df([18.0 for _ in range(30)])

    result = classify_market_regime(
        MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
        MarketRegimeConfig(),
    )
    assert result.regime == "bullish_trend"
    assert "allow_swing_long" in allowed_actions_for_regime(result.regime)


def test_classify_bearish_trend() -> None:
    kospi = _series_df([200 - i for i in range(30)])
    sp500 = _series_df([300 - i * 1.1 for i in range(30)])
    vol = _vol_df([20.0 for _ in range(30)])

    result = classify_market_regime(
        MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
        MarketRegimeConfig(),
    )
    assert result.regime == "bearish_trend"
    actions = allowed_actions_for_regime(result.regime)
    assert "allow_small_mean_reversion" in actions
    assert "tighten_stop_loss" in actions


def test_classify_sideways() -> None:
    flat = [100.0 + (0.05 if i % 2 == 0 else -0.05) for i in range(30)]
    kospi = _series_df(flat)
    sp500 = _series_df(flat)
    vol = _vol_df([16.0 for _ in range(30)])

    result = classify_market_regime(
        MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
        MarketRegimeConfig(),
    )
    assert result.regime == "sideways"


def test_classify_high_volatility_risk_overrides_trend() -> None:
    up = [100 + i for i in range(30)]
    kospi = _series_df(up)
    sp500 = _series_df(up)
    # high and rising volatility should force risk regime.
    vol = _vol_df([25 + i * 0.3 for i in range(30)])

    result = classify_market_regime(
        MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
        MarketRegimeConfig(high_volatility_threshold=28.0),
    )
    assert result.regime == "high_volatility_risk"
    actions = allowed_actions_for_regime(result.regime)
    assert "block_new_buy" in actions
    assert "only_risk_reduction" in actions
