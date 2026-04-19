"""RSI red/blue 플래그 헬퍼 단위 테스트(합성 분봉)."""

from __future__ import annotations

import pandas as pd

from app.strategy.rsi_flag_helpers import (
    evaluate_rsi_blue_flag_sell,
    evaluate_rsi_red_flag_buy,
    rsi_blue_flag_sell,
    rsi_red_flag_buy,
)


def _ohlcv_frame(n: int, *, drift: float = 0.0, vol: float = 1_000_000.0) -> pd.DataFrame:
    rows = []
    base = 100.0
    for i in range(n):
        c = base + drift * i
        o = c - 0.05
        h = c + 0.2
        low = c - 0.2
        rows.append(
            {
                "date": pd.Timestamp(f"2026-04-18 09:{i:02d}:00"),
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": vol * (1.05 + 0.01 * (i % 5)),
            }
        )
    return pd.DataFrame(rows)


def test_red_flag_insufficient_bars():
    sub = _ohlcv_frame(10)
    r = evaluate_rsi_red_flag_buy(sub)
    assert r["rsi_red_flag_buy"] is False
    assert "insufficient" in (r.get("rsi_red_flag_reason") or "").lower()


def test_blue_flag_insufficient_bars():
    sub = _ohlcv_frame(20)
    b = evaluate_rsi_blue_flag_sell(sub)
    assert b["rsi_blue_flag_sell"] is False


def test_red_oversold_turn_up_pattern():
    """RSI(7) 급락 후 반등 패턴을 합성."""
    n = 40
    prices = [100.0 - i * 0.35 for i in range(30)]  # 하락
    prices += [prices[-1] + i * 0.12 for i in range(1, 11)]  # 반등
    rows = []
    for i, c in enumerate(prices):
        o = c - 0.02
        rows.append(
            {
                "date": pd.Timestamp(f"2026-04-18 09:{i:02d}:00"),
                "open": o,
                "high": c + 0.15,
                "low": c - 0.15,
                "close": c,
                "volume": 2_000_000.0 * (1.1 if i >= 30 else 1.0),
            }
        )
    sub = pd.DataFrame(rows)
    r = evaluate_rsi_red_flag_buy(sub)
    assert "rsi_red_path_hits" in r
    assert isinstance(r.get("rsi_red_flag_reason"), str)


def test_public_aliases_match_evaluate_functions():
    sub = _ohlcv_frame(30)
    assert rsi_red_flag_buy(sub) == evaluate_rsi_red_flag_buy(sub)
    assert rsi_blue_flag_sell(sub) == evaluate_rsi_blue_flag_sell(sub)


def test_final_betting_feasible_vs_min_shares_math():
    """종가베팅 최소 배분(20%) vs 리스크 상한 정합성(순수 산술)."""
    eq = 50_000_000.0
    min_pct = 20.0
    max_pct = 25.0
    px = 70_000.0
    q_min = max(1, int((eq * (min_pct / 100.0)) / px))
    q_cap = max(1, int((eq * (max_pct / 100.0)) / px))
    assert q_min <= q_cap
    # 리스크 수량이 극단적으로 작다고 가정
    q_risk = 50
    feasible = min(q_risk, q_cap)
    assert feasible < q_min  # 이 경우 진입은 차단되어야 함(테스트는 부등식만 확인)
    assert q_min >= 142  # 대략 20% 노셔널 주수 하한
