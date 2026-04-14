from __future__ import annotations

import pandas as pd

from app.strategy.base_strategy import StrategyContext
from app.strategy.swing_relaxed_strategy import SwingRelaxedStrategy
from app.strategy.swing_relaxed_v2_strategy import SwingRelaxedV2Strategy


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
