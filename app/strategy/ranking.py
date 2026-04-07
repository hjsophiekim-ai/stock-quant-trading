from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from app.strategy.indicators import add_basic_indicators

MarketRegime = Literal["bullish_trend", "bearish_trend", "sideways", "high_volatility_risk"]


@dataclass(frozen=True)
class RankingWeights:
    relative_strength: float = 0.30
    ma_alignment: float = 0.25
    volume_growth: float = 0.15
    volatility_quality: float = 0.15
    regime_fit: float = 0.15


@dataclass(frozen=True)
class RankedCandidate:
    symbol: str
    total_score: float
    factor_scores: dict[str, float]
    reasons: list[str]


@dataclass(frozen=True)
class RankingReportRow:
    symbol: str
    total_score: float
    relative_strength: float
    ma_alignment: float
    volume_growth: float
    volatility_quality: float
    regime_fit: float
    reason_text: str


def rank_candidates(
    *,
    prices_df: pd.DataFrame,
    candidate_symbols: list[str],
    regime: MarketRegime,
    top_n: int,
    weights: RankingWeights = RankingWeights(),
) -> list[RankedCandidate]:
    if top_n <= 0 or not candidate_symbols:
        return []

    rows = []
    for symbol in candidate_symbols:
        s_df = prices_df[prices_df["symbol"] == symbol].sort_values("date")
        if s_df.empty:
            continue
        e = add_basic_indicators(s_df)
        latest = e.iloc[-1]
        ret_60 = float(latest["ret_60d_pct"]) if pd.notna(latest["ret_60d_pct"]) else 0.0
        ma20 = float(latest["ma20"]) if pd.notna(latest["ma20"]) else float(latest["close"])
        ma60 = float(latest["ma60"]) if pd.notna(latest["ma60"]) else float(latest["close"])
        close = float(latest["close"])
        vol20 = float(latest["vol20"]) if pd.notna(latest["vol20"]) and float(latest["vol20"]) > 0 else 1.0
        vol_ratio = float(latest["volume"]) / vol20
        rets = s_df["close"].pct_change().dropna()
        vol_std_pct = float(rets.tail(20).std() * 100.0) if not rets.empty else 0.0
        rows.append(
            {
                "symbol": symbol,
                "ret_60": ret_60,
                "ma_spread_pct": ((ma20 - ma60) / close) * 100.0 if close > 0 else 0.0,
                "vol_ratio": vol_ratio,
                "vol_std_pct": vol_std_pct,
            }
        )

    if not rows:
        return []

    snap = pd.DataFrame(rows)
    snap["relative_strength_score"] = _percentile_score(snap["ret_60"])
    snap["ma_alignment_score"] = snap["ma_spread_pct"].apply(lambda x: _clip01((x + 2.0) / 6.0))
    snap["volume_growth_score"] = snap["vol_ratio"].apply(lambda x: _clip01((x - 0.8) / 1.2))
    snap["volatility_quality_score"] = snap["vol_std_pct"].apply(lambda x: _clip01(1.0 - (x / 4.0)))
    snap["regime_fit_score"] = snap.apply(lambda r: _regime_fit_score(regime, r["ret_60"], r["ma_spread_pct"], r["vol_std_pct"]), axis=1)
    snap["total_score"] = (
        snap["relative_strength_score"] * weights.relative_strength
        + snap["ma_alignment_score"] * weights.ma_alignment
        + snap["volume_growth_score"] * weights.volume_growth
        + snap["volatility_quality_score"] * weights.volatility_quality
        + snap["regime_fit_score"] * weights.regime_fit
    )

    ranked = snap.sort_values("total_score", ascending=False).head(top_n)
    results: list[RankedCandidate] = []
    for _, row in ranked.iterrows():
        factor_scores = {
            "relative_strength": float(row["relative_strength_score"]),
            "ma_alignment": float(row["ma_alignment_score"]),
            "volume_growth": float(row["volume_growth_score"]),
            "volatility_quality": float(row["volatility_quality_score"]),
            "regime_fit": float(row["regime_fit_score"]),
        }
        reasons = [
            f"RS={factor_scores['relative_strength']:.2f}",
            f"MA={factor_scores['ma_alignment']:.2f}",
            f"VOL={factor_scores['volume_growth']:.2f}",
            f"VQ={factor_scores['volatility_quality']:.2f}",
            f"REG={factor_scores['regime_fit']:.2f}",
        ]
        results.append(
            RankedCandidate(
                symbol=str(row["symbol"]),
                total_score=float(row["total_score"]),
                factor_scores=factor_scores,
                reasons=reasons,
            )
        )
    return results


def build_ranking_report_rows(ranked: list[RankedCandidate]) -> list[RankingReportRow]:
    rows: list[RankingReportRow] = []
    for c in ranked:
        rows.append(
            RankingReportRow(
                symbol=c.symbol,
                total_score=c.total_score,
                relative_strength=float(c.factor_scores.get("relative_strength", 0.0)),
                ma_alignment=float(c.factor_scores.get("ma_alignment", 0.0)),
                volume_growth=float(c.factor_scores.get("volume_growth", 0.0)),
                volatility_quality=float(c.factor_scores.get("volatility_quality", 0.0)),
                regime_fit=float(c.factor_scores.get("regime_fit", 0.0)),
                reason_text=" | ".join(c.reasons),
            )
        )
    return rows


def _regime_fit_score(regime: MarketRegime, ret_60: float, ma_spread_pct: float, vol_std_pct: float) -> float:
    if regime == "bullish_trend":
        return _clip01((ret_60 / 12.0) * 0.6 + ((ma_spread_pct + 1.0) / 4.0) * 0.4)
    if regime == "bearish_trend":
        # Defensive preference: low volatility and less trend damage.
        return _clip01((1.0 - min(abs(ret_60) / 10.0, 1.0)) * 0.5 + (1.0 - min(vol_std_pct / 3.0, 1.0)) * 0.5)
    if regime == "sideways":
        return _clip01((1.0 - min(abs(ma_spread_pct) / 2.0, 1.0)) * 0.5 + (1.0 - min(vol_std_pct / 3.0, 1.0)) * 0.5)
    return 0.0


def _percentile_score(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype="float64")
    return series.rank(pct=True).astype("float64")


def _clip01(x: float) -> float:
    if x < 0:
        return 0.0
    if x > 1:
        return 1.0
    return float(x)
