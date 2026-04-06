from __future__ import annotations

from dataclasses import dataclass, field
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
    sideways_abs_return_threshold_pct: float = 1.0
    sideways_ma_slope_threshold_pct: float = 0.2
    lookback_days: int = 20
    bearish_allow_small_reversion: bool = True


@dataclass(frozen=True)
class MarketRegimeInputs:
    kospi: pd.DataFrame
    sp500: pd.DataFrame
    volatility: pd.DataFrame


@dataclass(frozen=True)
class MarketRegimeFeatures:
    kospi_return_pct: float
    sp500_return_pct: float
    kospi_ma_slope_pct: float
    sp500_ma_slope_pct: float
    volatility_level: float
    volatility_rising: bool


@dataclass(frozen=True)
class MarketRegimeResult:
    regime: MarketRegime
    features: MarketRegimeFeatures
    reasons: list[str]


REGIME_ACTIONS: dict[MarketRegime, list[StrategyAction]] = {
    "bullish_trend": ["allow_swing_long", "reduce_position_size"],
    "bearish_trend": ["allow_small_mean_reversion", "tighten_stop_loss", "reduce_position_size"],
    "sideways": ["allow_small_mean_reversion", "reduce_position_size", "tighten_stop_loss"],
    "high_volatility_risk": ["block_new_buy", "only_risk_reduction", "tighten_stop_loss"],
}


def classify_market_regime(inputs: MarketRegimeInputs, config: MarketRegimeConfig) -> MarketRegimeResult:
    features = compute_regime_features(inputs, config)
    reasons: list[str] = []

    if features.volatility_level >= config.high_volatility_threshold or features.volatility_rising:
        reasons.append("Volatility risk is elevated")
        return MarketRegimeResult(regime="high_volatility_risk", features=features, reasons=reasons)

    both_up = (
        features.kospi_return_pct >= config.bullish_return_threshold_pct
        and features.sp500_return_pct >= config.bullish_return_threshold_pct
        and features.kospi_ma_slope_pct > 0
        and features.sp500_ma_slope_pct > 0
    )
    if both_up:
        reasons.append("KOSPI and S&P500 are in rising trend")
        return MarketRegimeResult(regime="bullish_trend", features=features, reasons=reasons)

    both_down = (
        features.kospi_return_pct <= config.bearish_return_threshold_pct
        and features.sp500_return_pct <= config.bearish_return_threshold_pct
        and features.kospi_ma_slope_pct < 0
        and features.sp500_ma_slope_pct < 0
    )
    if both_down:
        reasons.append("KOSPI and S&P500 are in falling trend")
        return MarketRegimeResult(regime="bearish_trend", features=features, reasons=reasons)

    sideways_like = (
        abs(features.kospi_return_pct) <= config.sideways_abs_return_threshold_pct
        and abs(features.sp500_return_pct) <= config.sideways_abs_return_threshold_pct
        and abs(features.kospi_ma_slope_pct) <= config.sideways_ma_slope_threshold_pct
        and abs(features.sp500_ma_slope_pct) <= config.sideways_ma_slope_threshold_pct
    )
    if sideways_like:
        reasons.append("Index returns and MA slopes are flat")
        return MarketRegimeResult(regime="sideways", features=features, reasons=reasons)

    if features.kospi_ma_slope_pct > 0 and features.sp500_ma_slope_pct > 0:
        reasons.append("Trend mildly positive")
        return MarketRegimeResult(regime="bullish_trend", features=features, reasons=reasons)

    reasons.append("Defaulting to cautious sideways regime")
    return MarketRegimeResult(regime="sideways", features=features, reasons=reasons)


def allowed_actions_for_regime(regime: MarketRegime) -> list[StrategyAction]:
    return REGIME_ACTIONS[regime]


def compute_regime_features(inputs: MarketRegimeInputs, config: MarketRegimeConfig) -> MarketRegimeFeatures:
    lookback = config.lookback_days
    kospi_return = compute_recent_return_pct(inputs.kospi, close_col="close", lookback=lookback)
    sp500_return = compute_recent_return_pct(inputs.sp500, close_col="close", lookback=lookback)
    kospi_slope = compute_ma_slope_pct(inputs.kospi, close_col="close", ma_window=20)
    sp500_slope = compute_ma_slope_pct(inputs.sp500, close_col="close", ma_window=20)
    vol_level, vol_rising = compute_volatility_state(inputs.volatility, value_col="value")

    return MarketRegimeFeatures(
        kospi_return_pct=kospi_return,
        sp500_return_pct=sp500_return,
        kospi_ma_slope_pct=kospi_slope,
        sp500_ma_slope_pct=sp500_slope,
        volatility_level=vol_level,
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


def compute_volatility_state(df: pd.DataFrame, *, value_col: str) -> tuple[float, bool]:
    _validate_columns(df, {"date", value_col})
    s = df.sort_values("date")[value_col].astype("float64")
    if s.empty:
        return 0.0, False
    latest = float(s.iloc[-1])
    rising = len(s) >= 2 and float(s.iloc[-1]) > float(s.iloc[-2])
    return latest, rising


def _validate_columns(df: pd.DataFrame, required: set[str]) -> None:
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
