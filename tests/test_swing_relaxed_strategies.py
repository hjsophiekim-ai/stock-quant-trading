from __future__ import annotations

import pandas as pd
from pandas import Series

from app.strategy.base_strategy import StrategyContext
from app.strategy.swing_relaxed_strategy import SwingRelaxedStrategy
from app.strategy.swing_relaxed_v2_strategy import (
    SwingRelaxedV2Strategy,
    _build_exit_signals_relaxed_v2,
)
from app.strategy.swing_strategy import SwingStrategyConfig


def _mock_prices() -> pd.DataFrame:
    rows: list[dict] = []
    symbols = ["005930", "000660"]
    base = pd.Timestamp("2025-01-01")
    for i in range(90):
        for idx, sym in enumerate(symbols):
            close = 100 + (i * (0.18 + idx * 0.02))
            open_ = close - (0.6 if i % 3 else -0.4)
            rows.append(
                {
                    "symbol": sym,
                    "date": base + pd.Timedelta(days=i),
                    "open": round(open_, 4),
                    "high": round(close + 1.2, 4),
                    "low": round(close - 1.2, 4),
                    "close": round(close, 4),
                    "volume": 1_000_000 + (idx * 100_000) + (i * 2000),
                }
            )
    return pd.DataFrame(rows)


def _mock_index() -> pd.DataFrame:
    base = pd.Timestamp("2025-01-01")
    rows = []
    for i in range(90):
        close = 2500 + i * 1.5
        rows.append({"date": base + pd.Timedelta(days=i), "close": close, "open": close - 1.0, "high": close + 1.0, "low": close - 1.0})
    return pd.DataFrame(rows)


def _context() -> StrategyContext:
    prices = _mock_prices()
    idx = _mock_index()
    portfolio = pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"])
    return StrategyContext(
        prices=prices,
        kospi_index=idx,
        sp500_index=idx.copy(),
        portfolio=portfolio,
        volatility_index=pd.DataFrame({"date": idx["date"], "value": [18.0] * len(idx)}),
    )


def test_relaxed_v1_records_last_diagnostics() -> None:
    strat = SwingRelaxedStrategy()
    _ = strat.generate_orders(_context())
    assert isinstance(strat.last_diagnostics, list)
    assert strat.last_diagnostics
    first = strat.last_diagnostics[0]
    assert "symbol" in first
    assert "blocked_reason" in first
    assert "entered" in first


def test_relaxed_v2_records_verbose_last_diagnostics() -> None:
    strat = SwingRelaxedV2Strategy()
    _ = strat.generate_orders(_context())
    assert isinstance(strat.last_diagnostics, list)
    assert strat.last_diagnostics
    first = strat.last_diagnostics[0]
    assert "v2_hit_count" in first
    assert "v2_detail" in first
    assert isinstance(first["v2_detail"], dict)


def test_relaxed_v2_tp1_partial_only_once_per_tick_state() -> None:
    """tp1_already_done=True 이면 동일 조건에서 TP1 분할 매도가 재발하지 않아야 함."""
    cfg = SwingStrategyConfig(first_take_profit_pct=5.0, second_take_profit_pct=20.0, time_exit_days=99)
    signal = {
        "close": 110.0,
        "ma20": 100.0,
        "atr_available": True,
        "atr_pct": 3.0,
    }
    pos = Series({"quantity": 10, "average_price": 100.0, "hold_days": 1})
    ex1, d1 = _build_exit_signals_relaxed_v2("005930", signal, pos, cfg, tp1_already_done=False)
    assert d1.get("exit_branch") == "tp1_partial"
    assert ex1 and ex1[0].reason == "swing_relaxed_v2_tp1_partial"
    ex2, d2 = _build_exit_signals_relaxed_v2("005930", signal, pos, cfg, tp1_already_done=True)
    assert d2.get("exit_branch") != "tp1_partial"
    assert not any(s.reason == "swing_relaxed_v2_tp1_partial" for s in ex2)


def test_relaxed_v2_atr_exit_mode_fallback_when_atr_unavailable() -> None:
    cfg = SwingStrategyConfig(first_take_profit_pct=99.0, second_take_profit_pct=99.0, time_exit_days=99)
    signal = {
        "close": 98.0,
        "ma20": 100.0,
        "atr_available": False,
        "atr_pct": 0.0,
    }
    pos = Series({"quantity": 10, "average_price": 100.0, "hold_days": 1})
    _, diag = _build_exit_signals_relaxed_v2("005930", signal, pos, cfg, tp1_already_done=False)
    assert diag.get("swing_atr_exit_mode") == "fallback_fixed_stop"
    assert diag.get("atr_available") is False
