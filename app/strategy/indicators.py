from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def pct_change(series: pd.Series, periods: int) -> pd.Series:
    return series.pct_change(periods=periods) * 100.0


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    value = 100 - (100 / (1 + rs))
    return value.fillna(100.0)


def is_bullish_candle(open_price: pd.Series, close_price: pd.Series) -> pd.Series:
    return close_price > open_price


def add_basic_indicators(df: pd.DataFrame) -> pd.DataFrame:
    required = {"close", "open", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns for indicators: {sorted(missing)}")

    out = df.copy()
    out["ma20"] = sma(out["close"], 20)
    out["ma60"] = sma(out["close"], 60)
    out["rsi14"] = rsi(out["close"], 14)
    out["ret_3d_pct"] = pct_change(out["close"], 3)
    out["ret_60d_pct"] = pct_change(out["close"], 60)
    out["vol20"] = sma(out["volume"], 20)
    out["is_bullish"] = is_bullish_candle(out["open"], out["close"])
    return out
