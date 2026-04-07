from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

MarketRegime = Literal["bullish_trend", "bearish_trend", "sideways", "high_volatility_risk"]
StrategyAction = Literal[
    "allow_swing_long",
    "allow_small_mean_reversion",
    "reduce_position_size",
    "tighten_stop_loss",
    "block_new_buy",
    "only_risk_reduction",
]


@dataclass(frozen=True)
class MarketRegimeConfig:
    bullish_return_threshold_pct: float = 2.0
    bearish_return_threshold_pct: float = -2.0
    high_volatility_threshold: float = 28.0
    high_volatility_rise_threshold: float = 2.0
    sideways_abs_return_threshold_pct: float = 1.0
    sideways_ma_slope_threshold_pct: float = 0.15
    ma_short_window: int = 20
    ma_mid_window: int = 60
    ma_long_window: int = 120
    lookback_days: int = 20
    volatility_lookback_days: int = 5


@dataclass(frozen=True)
class MarketRegimeInputs:
    kospi: pd.DataFrame
    sp500: pd.DataFrame
    volatility: pd.DataFrame


@dataclass(frozen=True)
class MarketRegimeFeatures:
    kospi_return_pct: float
    sp500_return_pct: float
    kospi_ma20_slope_pct: float
    kospi_ma60_slope_pct: float
    kospi_ma120_slope_pct: float
    sp500_ma20_slope_pct: float
    sp500_ma60_slope_pct: float
    sp500_ma120_slope_pct: float
    volatility_level: float
    volatility_change_pct: float
    volatility_rising: bool


@dataclass(frozen=True)
class MarketRegimeResult:
    regime: MarketRegime
    features: MarketRegimeFeatures
    reasons: list[str]


REGIME_ACTIONS: dict[MarketRegime, list[StrategyAction]] = {
    "bullish_trend": ["allow_swing_long", "tighten_stop_loss"],
    "bearish_trend": ["allow_small_mean_reversion", "tighten_stop_loss", "reduce_position_size"],
    "sideways": ["allow_small_mean_reversion", "reduce_position_size", "tighten_stop_loss"],
    "high_volatility_risk": ["block_new_buy", "only_risk_reduction", "tighten_stop_loss"],
}


def classify_market_regime(inputs: MarketRegimeInputs, config: MarketRegimeConfig) -> MarketRegimeResult:
    features = compute_regime_features(inputs, config)
    reasons: list[str] = []

    if (
        features.volatility_level >= config.high_volatility_threshold
        or features.volatility_change_pct >= config.high_volatility_rise_threshold
    ):
        reasons.append("Volatility risk is elevated")
        return MarketRegimeResult(regime="high_volatility_risk", features=features, reasons=reasons)

    kospi_all_up = _all_positive(
        features.kospi_ma20_slope_pct,
        features.kospi_ma60_slope_pct,
        features.kospi_ma120_slope_pct,
    )
    sp500_all_up = _all_positive(
        features.sp500_ma20_slope_pct,
        features.sp500_ma60_slope_pct,
        features.sp500_ma120_slope_pct,
    )
    both_up = (
        features.kospi_return_pct >= config.bullish_return_threshold_pct
        and features.sp500_return_pct >= config.bullish_return_threshold_pct
        and kospi_all_up
        and sp500_all_up
    )
    if both_up:
        reasons.append("KOSPI and S&P500 MA20/60/120 slopes are positive")
        return MarketRegimeResult(regime="bullish_trend", features=features, reasons=reasons)

    kospi_all_down = _all_negative(
        features.kospi_ma20_slope_pct,
        features.kospi_ma60_slope_pct,
        features.kospi_ma120_slope_pct,
    )
    sp500_all_down = _all_negative(
        features.sp500_ma20_slope_pct,
        features.sp500_ma60_slope_pct,
        features.sp500_ma120_slope_pct,
    )
    both_down = (
        features.kospi_return_pct <= config.bearish_return_threshold_pct
        and features.sp500_return_pct <= config.bearish_return_threshold_pct
        and kospi_all_down
        and sp500_all_down
    )
    if both_down:
        reasons.append("KOSPI and S&P500 MA20/60/120 slopes are negative")
        return MarketRegimeResult(regime="bearish_trend", features=features, reasons=reasons)

    sideways_like = (
        abs(features.kospi_return_pct) <= config.sideways_abs_return_threshold_pct
        and abs(features.sp500_return_pct) <= config.sideways_abs_return_threshold_pct
        and _all_abs_below(
            config.sideways_ma_slope_threshold_pct,
            features.kospi_ma20_slope_pct,
            features.kospi_ma60_slope_pct,
            features.kospi_ma120_slope_pct,
            features.sp500_ma20_slope_pct,
            features.sp500_ma60_slope_pct,
            features.sp500_ma120_slope_pct,
        )
    )
    if sideways_like:
        reasons.append("Index returns and MA20/60/120 slopes are flat")
        return MarketRegimeResult(regime="sideways", features=features, reasons=reasons)

    if kospi_all_up and sp500_all_up:
        reasons.append("Trend is positive but returns are not strong enough yet")
        return MarketRegimeResult(regime="bullish_trend", features=features, reasons=reasons)

    reasons.append("Defaulting to bearish for capital protection")
    return MarketRegimeResult(regime="bearish_trend", features=features, reasons=reasons)


def allowed_actions_for_regime(regime: MarketRegime) -> list[StrategyAction]:
    return REGIME_ACTIONS[regime]


def compute_regime_features(inputs: MarketRegimeInputs, config: MarketRegimeConfig) -> MarketRegimeFeatures:
    lookback = config.lookback_days
    kospi_return = compute_recent_return_pct(inputs.kospi, close_col="close", lookback=lookback)
    sp500_return = compute_recent_return_pct(inputs.sp500, close_col="close", lookback=lookback)
    kospi_ma20_slope = compute_ma_slope_pct(inputs.kospi, close_col="close", ma_window=config.ma_short_window)
    kospi_ma60_slope = compute_ma_slope_pct(inputs.kospi, close_col="close", ma_window=config.ma_mid_window)
    kospi_ma120_slope = compute_ma_slope_pct(inputs.kospi, close_col="close", ma_window=config.ma_long_window)
    sp500_ma20_slope = compute_ma_slope_pct(inputs.sp500, close_col="close", ma_window=config.ma_short_window)
    sp500_ma60_slope = compute_ma_slope_pct(inputs.sp500, close_col="close", ma_window=config.ma_mid_window)
    sp500_ma120_slope = compute_ma_slope_pct(inputs.sp500, close_col="close", ma_window=config.ma_long_window)
    vol_level, vol_rising, vol_change_pct = compute_volatility_state(
        inputs.volatility,
        value_col="value",
        lookback=config.volatility_lookback_days,
    )

    return MarketRegimeFeatures(
        kospi_return_pct=kospi_return,
        sp500_return_pct=sp500_return,
        kospi_ma20_slope_pct=kospi_ma20_slope,
        kospi_ma60_slope_pct=kospi_ma60_slope,
        kospi_ma120_slope_pct=kospi_ma120_slope,
        sp500_ma20_slope_pct=sp500_ma20_slope,
        sp500_ma60_slope_pct=sp500_ma60_slope,
        sp500_ma120_slope_pct=sp500_ma120_slope,
        volatility_level=vol_level,
        volatility_change_pct=vol_change_pct,
        volatility_rising=vol_rising,
    )


def compute_recent_return_pct(df: pd.DataFrame, *, close_col: str, lookback: int) -> float:
    _validate_columns(df, {"date", close_col})
    s = df.sort_values("date")[close_col].astype("float64")
    if len(s) < lookback + 1:
        return 0.0
    start = float(s.iloc[-(lookback + 1)])
    end = float(s.iloc[-1])
    if start <= 0:
        return 0.0
    return ((end / start) - 1.0) * 100.0


def compute_ma_slope_pct(df: pd.DataFrame, *, close_col: str, ma_window: int) -> float:
    _validate_columns(df, {"date", close_col})
    s = df.sort_values("date")[close_col].astype("float64")
    ma = s.rolling(window=ma_window, min_periods=ma_window).mean()
    if len(ma) < 2 or pd.isna(ma.iloc[-1]) or pd.isna(ma.iloc[-2]) or float(ma.iloc[-2]) == 0.0:
        return 0.0
    prev = float(ma.iloc[-2])
    curr = float(ma.iloc[-1])
    return ((curr / prev) - 1.0) * 100.0


def compute_volatility_state(df: pd.DataFrame, *, value_col: str, lookback: int) -> tuple[float, bool, float]:
    _validate_columns(df, {"date", value_col})
    s = df.sort_values("date")[value_col].astype("float64")
    if s.empty:
        return 0.0, False, 0.0
    latest = float(s.iloc[-1])
    rising = len(s) >= 2 and float(s.iloc[-1]) > float(s.iloc[-2])
    if len(s) < lookback + 1:
        return latest, rising, 0.0
    base = float(s.iloc[-(lookback + 1)])
    if base == 0.0:
        return latest, rising, 0.0
    change_pct = ((latest / base) - 1.0) * 100.0
    return latest, rising, change_pct


def _all_positive(*values: float) -> bool:
    return all(v > 0 for v in values)


def _all_negative(*values: float) -> bool:
    return all(v < 0 for v in values)


def _all_abs_below(threshold: float, *values: float) -> bool:
    return all(abs(v) <= threshold for v in values)


def _validate_columns(df: pd.DataFrame, required: set[str]) -> None:
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
