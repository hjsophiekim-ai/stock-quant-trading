"""
종목 스크리닝용 랭킹·필터.

- 리스크 게이트: MA60 상승, 최소 거래량 비율, 고변동·갭 과열 제외, 최소 데이터 길이
- 단면필터: 약 3개월(60거래일) 수익률 상위 P% (국면별 조정)
- 소프트랭킹: 상대강도·MA정렬·거래량·변동성 품질·국면 적합도 가중 점수(국면별 가중치)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.strategy.market_regime import MarketRegime


_REGIME_LABEL_KO: dict[str, str] = {
    "bullish_trend": "상승 추세",
    "bearish_trend": "하락 추세",
    "sideways": "횡보",
    "high_volatility_risk": "고변동·위험",
}


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
    """초보자용 한 줄 설명."""
    reasons_detail: list[str] = field(default_factory=list)
    """지표·점수 근거(상세)."""
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
    prev_close = float(prev["close"])
    open_px = float(cur["open"])
    gap_pct = ((open_px - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0
    vol_ratio = vol / vol20 if vol20 > 0 else 0.0
    vol_ok = bool(vol20 > 0 and vol_ratio >= 1.0)
    return {
        "symbol": symbol,
        "close": close,
        "ret_60": ret_60,
        "ma60": ma60,
        "ma60_prev": ma60_prev,
        "ma60_slope_pct": ma60_slope_pct,
        "ma60_rising": ma60_rising,
        "vol_ratio": vol_ratio,
        "vol_ok": vol_ok,
        "vol_std_pct": vol_std_pct,
        "gap_pct": gap_pct,
    }


def apply_screening_gates(
    rows: list[dict],
    *,
    max_vol_std_pct: float,
    max_abs_gap_pct: float,
    min_volume_ratio: float,
) -> tuple[list[dict], list[dict[str, object]], list[str]]:
    """
    리스크 최소화 게이트. 통과 종목 / 제외 레코드(symbol, stage, block_reasons) / 감사 로그.
    """
    passed: list[dict] = []
    exclusions: list[dict[str, object]] = []
    log: list[str] = []
    for r in rows:
        sym = str(r["symbol"])
        reasons: list[str] = []
        if pd.isna(r.get("ret_60")):
            reasons.append("60일 누적 수익률을 계산할 수 없어 제외합니다.")
        if not r.get("ma60_rising"):
            reasons.append("60일 이동평균선 기준 추세가 아직 약합니다(전일 대비 MA60이 낮거나 같음).")
        vr = float(r.get("vol_ratio") or 0.0)
        if vr < min_volume_ratio:
            reasons.append(
                f"거래량이 최근 20일 평균 대비 부족합니다(비율 {vr:.2f}, 기준 ≥{min_volume_ratio:.2f})."
            )
        vs = float(r.get("vol_std_pct") or 0.0)
        if vs > max_vol_std_pct:
            reasons.append(
                f"최근 20일 가격 변동성이 큽니다(일간 표준편차 환산 {vs:.2f}%, 기준 ≤{max_vol_std_pct:.2f}%)."
            )
        gp = float(r.get("gap_pct") or 0.0)
        if abs(gp) > max_abs_gap_pct:
            reasons.append(
                f"전일 대비 시가 갭이 큽니다(갭 {gp:.2f}%, 절대값 기준 ≤{max_abs_gap_pct:.2f}%)."
            )
        if reasons:
            exclusions.append({"symbol": sym, "stage": "risk_gate", "block_reasons": reasons})
            log.append(f"{sym}: 리스크게이트 제외 ({len(reasons)}건)")
            continue
        passed.append(r)
    return passed, exclusions, log


def apply_hard_filters(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """호환용 — 예전 MA60+당일거래량≥20일평균 근사(거래량비율≥1)."""
    p, _ex, log = apply_screening_gates(
        rows,
        max_vol_std_pct=99.0,
        max_abs_gap_pct=99.0,
        min_volume_ratio=1.0,
    )
    return p, log


def apply_return_top_percentile(
    rows: list[dict],
    *,
    top_pct: float = 0.30,
) -> tuple[list[dict], list[str], list[dict[str, object]], float | None]:
    """
    3개월(60일) 수익률 기준 상위 top_pct 비율만 통과.
    top_pct=0.3 → 상위 30% (누적분포 0.7 이상).
    """
    log: list[str] = []
    exclusions: list[dict[str, object]] = []
    if not rows:
        return [], log, exclusions, None
    rets = pd.Series([float(r["ret_60"]) for r in rows])
    thr = float(rets.quantile(1.0 - top_pct))
    out: list[dict] = []
    for r in rows:
        r60 = float(r["ret_60"])
        if r60 >= thr:
            out.append(r)
        else:
            sym = str(r["symbol"])
            exclusions.append(
                {
                    "symbol": sym,
                    "stage": "return_percentile",
                    "block_reasons": [
                        f"60일 수익률 {r60:.2f}%가 이번 선정에서 요구하는 상위 {top_pct * 100:.0f}% "
                        f"기준(임계 약 {thr:.2f}%)에 도달하지 못했습니다.",
                    ],
                }
            )
    log.append(f"3M수익률 상위 {top_pct*100:.0f}% 임계값={thr:.3f}% (통과 {len(out)}/{len(rows)})")
    return out, log, exclusions, thr


def weights_for_regime(regime: MarketRegime) -> ScreenerRankingWeights:
    """국면별 가중치 — 약세·횡보에서는 변동성 품질·국면 적합 비중을 높임."""
    if regime == "bearish_trend":
        return ScreenerRankingWeights(
            relative_strength=0.25,
            ma60_trend=0.18,
            volume_participation=0.14,
            volatility_quality=0.30,
            regime_fit=0.13,
        )
    if regime == "sideways":
        return ScreenerRankingWeights(
            relative_strength=0.28,
            ma60_trend=0.20,
            volume_participation=0.17,
            volatility_quality=0.20,
            regime_fit=0.15,
        )
    if regime == "high_volatility_risk":
        return ScreenerRankingWeights(
            relative_strength=0.22,
            ma60_trend=0.18,
            volume_participation=0.12,
            volatility_quality=0.35,
            regime_fit=0.13,
        )
    return ScreenerRankingWeights()


def _beginner_reason_lines(
    *,
    regime: MarketRegime,
    ret_60: float,
    ma60_slope_pct: float,
    vol_ratio: float,
    vol_std_pct: float,
    fs: dict[str, float],
) -> list[str]:
    rk = _REGIME_LABEL_KO.get(regime, str(regime))
    lines = [
        f"최근 약 3개월(60거래일) 수익률이 약 {ret_60:.1f}%로, 후보 중 상대적으로 우수한 편입니다.",
        f"60일 이평선이 우상향(기울기 약 {ma60_slope_pct:.2f}%)이라 단기 추세가 살아 있는 종목입니다.",
        f"거래량이 20일 평균 대비 {vol_ratio:.2f}배로, 유동성이 평소보다 충분합니다.",
        f"최근 20일 일간 가격 변동성은 약 {vol_std_pct:.2f}% 수준으로, 지나치게 들쭉날쭉하지 않게 관리되었습니다.",
        f"지금 시장 국면({rk})에 맞춰 점수를 매긴 결과, 종합 점수에서 상위에 들었습니다(국면 적합 {fs['regime_fit']:.2f}).",
    ]
    return lines


def rank_candidates(
    rows: list[dict],
    *,
    regime: MarketRegime,
    top_n: int,
    weights: ScreenerRankingWeights | None = None,
) -> list[ScreenedCandidate]:
    if not rows or top_n <= 0:
        return []
    w = weights or weights_for_regime(regime)
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
        snap["rs_score"] * w.relative_strength
        + snap["ma60_score"] * w.ma60_trend
        + snap["vol_score"] * w.volume_participation
        + snap["vq_score"] * w.volatility_quality
        + snap["reg_score"] * w.regime_fit
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
        detail = [
            f"60일수익률={float(r['ret_60']):.2f}% (RS백분위점수 {fs['relative_strength']:.2f})",
            f"MA60기울기={float(r['ma60_slope_pct']):.3f}% → 점수 {fs['ma60_trend']:.2f}",
            f"거래량비율={float(r['vol_ratio']):.2f} → 점수 {fs['volume_participation']:.2f}",
            f"20일변동성%={float(r['vol_std_pct']):.2f} → 품질 {fs['volatility_quality']:.2f}",
            f"국면({regime})적합도 {fs['regime_fit']:.2f}",
        ]
        simple = _beginner_reason_lines(
            regime=regime,
            ret_60=float(r["ret_60"]),
            ma60_slope_pct=float(r["ma60_slope_pct"]),
            vol_ratio=float(r["vol_ratio"]),
            vol_std_pct=float(r["vol_std_pct"]),
            fs=fs,
        )
        results.append(
            ScreenedCandidate(
                symbol=str(r["symbol"]),
                total_score=float(r["total"]),
                factor_scores=fs,
                reasons=simple,
                reasons_detail=detail,
                metrics={
                    "ret_60d_pct": float(r["ret_60"]),
                    "ma60_slope_pct": float(r["ma60_slope_pct"]),
                    "vol_ratio": float(r["vol_ratio"]),
                    "vol_std_pct": float(r["vol_std_pct"]),
                    "gap_pct": float(r["gap_pct"]),
                },
            )
        )
    return results


def screened_candidate_to_api_dict(c: ScreenedCandidate, *, regime: str) -> dict[str, object]:
    """대시보드/API용 단일 후보 페이로드."""
    return {
        "symbol": c.symbol,
        "score": round(c.total_score, 6),
        "total_score": round(c.total_score, 6),
        "factor_scores": {k: round(v, 6) for k, v in c.factor_scores.items()},
        "reasons": list(c.reasons),
        "reasons_detail": list(c.reasons_detail),
        "block_reasons": [],
        "metrics": {k: round(float(v), 6) for k, v in c.metrics.items()},
        "regime": regime,
    }


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
