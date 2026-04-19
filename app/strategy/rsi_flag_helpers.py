"""
RSI 기반 red-flag(매수 후보) / blue-flag(매도·청산 후보) 진단.

Paper/라이브 공통으로 재사용 가능한 순수 함수. UI 라벨이 아니라 코드·진단 필드명으로 의미를 고정한다.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.strategy.intraday_common import ema, rsi_wilder, session_vwap, volume_zscore_recent


def macd_histogram_series(close: pd.Series) -> pd.Series:
    """MACD 라인 − 시그널 = 히스토그램(추세 약화 감지용)."""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    line = ema12 - ema26
    sig = line.ewm(span=9, adjust=False).mean()
    return line - sig


def _empty_flags() -> dict[str, Any]:
    return {
        "rsi_red_flag_buy": False,
        "rsi_red_flag_reason": "",
        "rsi_blue_flag_sell": False,
        "rsi_blue_flag_reason": "",
        "rsi_red_path_hits": 0,
    }


def evaluate_rsi_red_flag_buy(sub: pd.DataFrame) -> dict[str, Any]:
    """
    Red flag 매수 후보: 과매도 회복·VWAP/단기 EMA 재탈환·변동성 플러시 후 반전 등(낙칼 단독 추격 차단).
    반환 dict에는 항상 rsi_red_flag_* / rsi_blue_flag_* 4키가 포함된다(blue는 여기서 미사용).
    """
    out = _empty_flags()
    if sub is None or sub.empty or len(sub) < 24:
        out["rsi_red_flag_reason"] = "insufficient_bars"
        out["rsi_red_path_hits"] = 0
        return out

    s = sub.sort_values("date")
    close = s["close"].astype(float)
    open_ = s["open"].astype(float)
    high = s["high"].astype(float)
    low = s["low"].astype(float)
    vol = s["volume"].astype(float)

    rsi7 = rsi_wilder(close, 7)
    rsi14 = rsi_wilder(close, 14)
    vw = session_vwap(s)
    ema3 = ema(close, 3)
    ema8 = ema(close, 8)

    r7 = float(rsi7.iloc[-1]) if len(rsi7) else 50.0
    r7_prev = float(rsi7.iloc[-2]) if len(rsi7) >= 2 else r7
    r14 = float(rsi14.iloc[-1]) if len(rsi14) else 50.0
    last_c = float(close.iloc[-1])
    last_o = float(open_.iloc[-1])
    prev_c = float(close.iloc[-2]) if len(close) >= 2 else last_c
    vwap_last = float(vw.iloc[-1]) if len(vw) else last_c
    e3 = float(ema3.iloc[-1]) if len(ema3) else last_c
    e8 = float(ema8.iloc[-1]) if len(ema8) else last_c

    vz = volume_zscore_recent(vol, 20)
    vol_ma = float(vol.iloc[-20:].mean()) if len(vol) >= 8 else float(vol.mean())
    last_v = float(vol.iloc[-1])
    vol_ok = (vz is not None and vz > -0.55) or (vol_ma > 0 and last_v >= vol_ma * 0.92)

    # Path A: RSI(7) 과매도 후 상향 전환
    path_a = bool(len(rsi7) >= 3 and r7_prev <= 28.0 and r7 > r7_prev)

    # Path B: RSI(14) 과매도 + VWAP/단기 EMA 재탈환
    path_b = bool(
        r14 <= 35.0
        and last_c >= vwap_last * 0.998
        and e3 >= e8 * 0.9995
    )

    # Path C: 변동성 플러시 후 양봉(직전 구간 RSI 낮았다가 반전)
    rng = max(float(high.iloc[-1] - low.iloc[-1]), 1e-9)
    body_ok = last_c >= last_o
    path_c = bool(
        body_ok
        and len(rsi7) >= 3
        and float(rsi7.iloc[-2]) <= 32.0
        and r7 > r7_prev
        and last_c >= prev_c * 0.998
    )

    # 낙칼: 직전 대비 RSI·가격 동반 급락
    falling_knife = bool(
        len(close) >= 2
        and last_c < prev_c * 0.996
        and last_c < last_o
        and r7 < r7_prev
        and r7 < 24.0
    )

    score = int(path_a) + int(path_b) + int(path_c)
    reasons: list[str] = []
    if path_a:
        reasons.append("rsi7_oversold_turn_up")
    if path_b:
        reasons.append("rsi14_oversold_vwap_ema")
    if path_c:
        reasons.append("vol_flush_bull_reversal")

    ok = score >= 2 and vol_ok and (not falling_knife)
    if not vol_ok:
        reasons.append("volume_confirmation_fail")
    if falling_knife:
        reasons.append("blocked_falling_knife")
    if score < 2:
        reasons.append(f"score_low({score}<2)")

    out["rsi_red_flag_buy"] = bool(ok)
    out["rsi_red_flag_reason"] = ";".join(reasons) if reasons else "none"
    out["rsi_red_path_hits"] = int(score)
    return out


def evaluate_rsi_blue_flag_sell(sub: pd.DataFrame) -> dict[str, Any]:
    """
    Blue flag 청산 후보: 과매수 꺾임·MACD 히스토그램 약화·VWAP 위 확장 후 실패 캔들.
    """
    out = _empty_flags()
    if sub is None or sub.empty or len(sub) < 30:
        out["rsi_blue_flag_reason"] = "insufficient_bars"
        return out

    s = sub.sort_values("date")
    close = s["close"].astype(float)
    open_ = s["open"].astype(float)
    high = s["high"].astype(float)
    low = s["low"].astype(float)

    rsi7 = rsi_wilder(close, 7)
    rsi14 = rsi_wilder(close, 14)
    vw = session_vwap(s)
    hist = macd_histogram_series(close)

    r7 = float(rsi7.iloc[-1]) if len(rsi7) else 50.0
    r7_prev = float(rsi7.iloc[-2]) if len(rsi7) >= 2 else r7
    r14 = float(rsi14.iloc[-1]) if len(rsi14) else 50.0
    last_c = float(close.iloc[-1])
    last_o = float(open_.iloc[-1])
    vwap_last = float(vw.iloc[-1]) if len(vw) else last_c
    h_now = float(hist.iloc[-1]) if len(hist) else 0.0
    h_lag = float(hist.iloc[-3]) if len(hist) >= 3 else h_now

    # B1: RSI(7) 고과매수 + 꺾임
    b1 = bool(r7 >= 72.0 and r7 < r7_prev)

    # B2: RSI(14) 고구간 + MACD 히스토그램 약화
    b2 = bool(r14 >= 65.0 and h_now < h_lag * 0.92)

    # B3: VWAP 위 과확장 후 음봉 실패
    extended = last_c > vwap_last * 1.0025
    bearish = last_c < last_o
    b3 = bool(extended and bearish and r14 >= 58.0 and last_c < float(high.iloc[-1]) * 0.998)

    reasons: list[str] = []
    if b1:
        reasons.append("rsi7_overbought_rollover")
    if b2:
        reasons.append("rsi14_high_macd_hist_weakening")
    if b3:
        reasons.append("vwap_stretch_failure_candle")

    ok = bool(b1 or b2 or b3)
    out["rsi_blue_flag_sell"] = ok
    out["rsi_blue_flag_reason"] = ";".join(reasons) if reasons else "none"
    return out
