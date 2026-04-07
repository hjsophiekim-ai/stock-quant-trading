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
    kospi = _series_df([100 + i * 0.8 for i in range(180)])
    sp500 = _series_df([200 + i * 1.1 for i in range(180)])
    vol = _vol_df([18.0 for _ in range(180)])

    result = classify_market_regime(
        MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
        MarketRegimeConfig(),
    )
    assert result.regime == "bullish_trend"
    assert "allow_swing_long" in allowed_actions_for_regime(result.regime)


def test_classify_bearish_trend() -> None:
    kospi = _series_df([300 - i * 0.9 for i in range(180)])
    sp500 = _series_df([400 - i * 1.1 for i in range(180)])
    vol = _vol_df([20.0 for _ in range(180)])

    result = classify_market_regime(
        MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
        MarketRegimeConfig(),
    )
    assert result.regime == "bearish_trend"
    actions = allowed_actions_for_regime(result.regime)
    assert "allow_small_mean_reversion" in actions
    assert "tighten_stop_loss" in actions


def test_classify_sideways() -> None:
    flat = [100.0 + (0.03 if i % 2 == 0 else -0.03) for i in range(180)]
    kospi = _series_df(flat)
    sp500 = _series_df(flat)
    vol = _vol_df([16.0 for _ in range(180)])

    result = classify_market_regime(
        MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
        MarketRegimeConfig(),
    )
    assert result.regime == "sideways"


def test_classify_high_volatility_risk_overrides_trend() -> None:
    up = [100 + i * 0.8 for i in range(180)]
    kospi = _series_df(up)
    sp500 = _series_df(up)
    # high and rising volatility should force risk regime.
    vol = _vol_df([25 + i * 0.25 for i in range(180)])

    result = classify_market_regime(
        MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
        MarketRegimeConfig(high_volatility_threshold=28.0),
    )
    assert result.regime == "high_volatility_risk"
    actions = allowed_actions_for_regime(result.regime)
    assert "block_new_buy" in actions
    assert "only_risk_reduction" in actions


def test_classify_high_volatility_risk_on_fast_spike_with_custom_config() -> None:
    up = [100 + i for i in range(180)]
    kospi = _series_df(up)
    sp500 = _series_df(up)
    vol = _vol_df([18.0 for _ in range(174)] + [18.2, 18.4, 20.5, 22.0, 23.0, 24.0])

    result = classify_market_regime(
        MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
        MarketRegimeConfig(
            high_volatility_threshold=40.0,
            high_volatility_rise_threshold=8.0,
            volatility_lookback_days=5,
        ),
    )
    assert result.regime == "high_volatility_risk"


def test_bearish_when_ma_directions_diverge() -> None:
    # short-term rebound but long-term trend still weak -> defensive default.
    down_then_up = [300 - i * 1.5 for i in range(150)] + [75 + i * 0.8 for i in range(30)]
    kospi = _series_df(down_then_up)
    sp500 = _series_df(down_then_up)
    vol = _vol_df([16.0 for _ in range(180)])

    result = classify_market_regime(
        MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
        MarketRegimeConfig(),
    )
    assert result.regime == "bearish_trend"
