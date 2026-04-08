"""
종목 스크리닝용 랭킹·필터.

- 하드필터: MA60 상승, 거래량 ≥ N일 평균, 최소 데이터 길이
- 단면필터: 약 3개월(60거래일) 수익률 상위 P% (기본 30%)
- 소프트랭킹: 상대강도·MA정렬·거래량·변동성 품질·국면 적합도 가중 점수
"""

from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd

from app.strategy.market_regime import MarketRegime


@dataclass(frozen=True)
class ScreenerRankingWeights:
    relative_strength: float = 0.32
    ma60_trend: float = 0.22
    volume_participation: float = 0.18
    volatility_quality: float = 0.13
    regime_fit: float = 0.15


@dataclass
class ScreenedCandidate:
    symbol: str
    total_score: float
    factor_scores: dict[str, float]
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _percentile_rank(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype="float64")
    return series.rank(pct=True).astype("float64")


def _regime_fit(regime: MarketRegime, ret_60: float, ma60_slope_pct: float, vol_std_pct: float) -> float:
    if regime == "bullish_trend":
        return _clip01((ret_60 / 15.0) * 0.55 + ((ma60_slope_pct + 0.5) / 3.0) * 0.45)
    if regime == "bearish_trend":
        return _clip01((1.0 - min(abs(ret_60) / 12.0, 1.0)) * 0.55 + (1.0 - min(vol_std_pct / 3.5, 1.0)) * 0.45)
    if regime == "sideways":
        return _clip01((1.0 - min(abs(ma60_slope_pct) / 1.5, 1.0)) * 0.5 + (1.0 - min(vol_std_pct / 3.5, 1.0)) * 0.5)
    return 0.0


def build_symbol_feature_row(prices_df: pd.DataFrame, symbol: str) -> dict | None:
    """단일 종목 최신 행 지표. 부족하면 None."""
    from app.strategy.indicators import add_basic_indicators

    s = prices_df[prices_df["symbol"] == symbol].sort_values("date")
    if len(s) < 65:
        return None
    e = add_basic_indicators(s)
    cur = e.iloc[-1]
    prev = e.iloc[-2]
    ma60 = float(cur["ma60"]) if pd.notna(cur["ma60"]) else float("nan")
    ma60_prev = float(prev["ma60"]) if pd.notna(prev["ma60"]) else float("nan")
    close = float(cur["close"])
    ret_60 = float(cur["ret_60d_pct"]) if pd.notna(cur["ret_60d_pct"]) else float("nan")
    vol = float(cur["volume"])
    vol20 = float(cur["vol20"]) if pd.notna(cur["vol20"]) and float(cur["vol20"]) > 0 else 0.0
    ma60_slope_pct = ((ma60 - ma60_prev) / ma60_prev * 100.0) if ma60_prev > 0 else 0.0
    rets = s["close"].pct_change().dropna()
    vol_std_pct = float(rets.tail(20).std() * 100.0) if len(rets) >= 5 else 0.0
    ma60_rising = bool(ma60 > ma60_prev) if ma60 == ma60 and ma60_prev == ma60_prev else False
    vol_ok = bool(vol20 > 0 and vol >= vol20)
    return {
        "symbol": symbol,
        "close": close,
        "ret_60": ret_60,
        "ma60": ma60,
        "ma60_prev": ma60_prev,
        "ma60_slope_pct": ma60_slope_pct,
        "ma60_rising": ma60_rising,
        "vol_ratio": vol / vol20 if vol20 > 0 else 0.0,
        "vol_ok": vol_ok,
        "vol_std_pct": vol_std_pct,
    }


def apply_hard_filters(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """MA60 상승 + 거래량 평균 이상."""
    passed: list[dict] = []
    log: list[str] = []
    for r in rows:
        sym = r["symbol"]
        if not r.get("ma60_rising"):
            log.append(f"{sym}: MA60 미상승 제외")
            continue
        if not r.get("vol_ok"):
            log.append(f"{sym}: 거래량<20일평균 제외")
            continue
        if pd.isna(r.get("ret_60")):
            log.append(f"{sym}: 60일수익률 없음 제외")
            continue
        passed.append(r)
    return passed, log


def apply_return_top_percentile(
    rows: list[dict],
    *,
    top_pct: float = 0.30,
) -> tuple[list[dict], list[str], float | None]:
    """
    3개월(60일) 수익률 기준 상위 top_pct 비율만 통과.
    top_pct=0.3 → 상위 30% (누적분포 0.7 이상).
    """
    log: list[str] = []
    if not rows:
        return [], log, None
    rets = pd.Series([float(r["ret_60"]) for r in rows])
    thr = float(rets.quantile(1.0 - top_pct))
    out = [r for r in rows if float(r["ret_60"]) >= thr]
    log.append(f"3M수익률 상위 {top_pct*100:.0f}% 임계값={thr:.3f}% (통과 {len(out)}/{len(rows)})")
    return out, log, thr


def rank_candidates(
    rows: list[dict],
    *,
    regime: MarketRegime,
    top_n: int,
    weights: ScreenerRankingWeights = ScreenerRankingWeights(),
) -> list[ScreenedCandidate]:
    if not rows or top_n <= 0:
        return []
    snap = pd.DataFrame(rows)
    snap["rs_score"] = _percentile_rank(snap["ret_60"])
    snap["ma60_score"] = snap["ma60_slope_pct"].apply(lambda x: _clip01((float(x) + 0.2) / 1.2))
    snap["vol_score"] = snap["vol_ratio"].apply(lambda x: _clip01((float(x) - 0.9) / 1.5))
    snap["vq_score"] = snap["vol_std_pct"].apply(lambda x: _clip01(1.0 - min(float(x) / 4.0, 1.0)))
    snap["reg_score"] = snap.apply(
        lambda r: _regime_fit(regime, float(r["ret_60"]), float(r["ma60_slope_pct"]), float(r["vol_std_pct"])),
        axis=1,
    )
    snap["total"] = (
        snap["rs_score"] * weights.relative_strength
        + snap["ma60_score"] * weights.ma60_trend
        + snap["vol_score"] * weights.volume_participation
        + snap["vq_score"] * weights.volatility_quality
        + snap["reg_score"] * weights.regime_fit
    )
    snap = snap.sort_values("total", ascending=False).head(top_n)
    results: list[ScreenedCandidate] = []
    for _, r in snap.iterrows():
        fs = {
            "relative_strength": float(r["rs_score"]),
            "ma60_trend": float(r["ma60_score"]),
            "volume_participation": float(r["vol_score"]),
            "volatility_quality": float(r["vq_score"]),
            "regime_fit": float(r["reg_score"]),
        }
        reasons = [
            f"60일수익률={float(r['ret_60']):.2f}% (RS백분위점수 {fs['relative_strength']:.2f})",
            f"MA60기울기={float(r['ma60_slope_pct']):.3f}% → 점수 {fs['ma60_trend']:.2f}",
            f"거래량비율={float(r['vol_ratio']):.2f} → 점수 {fs['volume_participation']:.2f}",
            f"20일변동성%={float(r['vol_std_pct']):.2f} → 품질 {fs['volatility_quality']:.2f}",
            f"국면({regime})적합도 {fs['regime_fit']:.2f}",
        ]
        results.append(
            ScreenedCandidate(
                symbol=str(r["symbol"]),
                total_score=float(r["total"]),
                factor_scores=fs,
                reasons=reasons,
                metrics={
                    "ret_60d_pct": float(r["ret_60"]),
                    "ma60_slope_pct": float(r["ma60_slope_pct"]),
                    "vol_ratio": float(r["vol_ratio"]),
                },
            )
        )
    return results


def regime_adjusted_top_n_and_percentile(
    regime: MarketRegime,
    base_top_n: int,
    base_top_return_pct: float,
) -> tuple[int, float, list[str]]:
    """시장이 나쁠수록 후보 축소·상위 비율 강화."""
    reasons: list[str] = []
    n = base_top_n
    p = base_top_return_pct
    if regime == "high_volatility_risk":
        return 0, p, reasons + ["고변동 국면: 신규 후보 차단(block)"]
    if regime == "bearish_trend":
        n = max(1, int(round(base_top_n * 0.5)))
        p = min(0.20, base_top_return_pct)
        reasons.append(f"약세 국면: top_n {base_top_n}→{n}, 상위수익률구간 {base_top_return_pct:.0%}→{p:.0%}")
    elif regime == "sideways":
        n = max(1, int(round(base_top_n * 0.75)))
        p = min(0.25, base_top_return_pct)
        reasons.append(f"횡보 국면: top_n {base_top_n}→{n}, 상위수익률구간 완화 {p:.0%}")
    else:
        reasons.append("강세 국면: 기본 스크리닝 강도 유지")
    return n, p, reasons
