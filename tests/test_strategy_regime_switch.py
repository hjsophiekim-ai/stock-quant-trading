from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from app.strategy.base_strategy import BaseStrategy, StrategyContext, StrategySignal
from app.strategy.swing_strategy import SwingStrategy


@dataclass
class _DummyStrategy(BaseStrategy):
    name: str

    def generate_signals(self, context: StrategyContext) -> list[StrategySignal]:
        _ = context
        return [
            StrategySignal(
                symbol="005930",
                side="buy",
                quantity=1,
                price=None,
                stop_loss_pct=3.0,
                reason=f"{self.name} selected",
                strategy_name=self.name,
            )
        ]


def _make_prices() -> pd.DataFrame:
    base = datetime(2026, 1, 1)
    rows: list[dict[str, object]] = []
    for i in range(80):
        rows.append(
            {
                "symbol": "005930",
                "date": base + timedelta(days=i),
                "open": 100 + i * 0.3,
                "high": 101 + i * 0.3,
                "low": 99 + i * 0.3,
                "close": 100 + i * 0.3,
                "volume": 1_000_000 + i * 1000,
            }
        )
    return pd.DataFrame(rows)


def _make_index(start: float, step: float) -> pd.DataFrame:
    base = datetime(2026, 1, 1)
    return pd.DataFrame([{"date": base + timedelta(days=i), "close": start + i * step} for i in range(40)])


def _make_vol(value: float, rising: bool = False) -> pd.DataFrame:
    base = datetime(2026, 1, 1)
    vals = [value + (i * 0.2 if rising else 0.0) for i in range(40)]
    return pd.DataFrame([{"date": base + timedelta(days=i), "value": v} for i, v in enumerate(vals)])


def test_regime_switch_to_bull_strategy(monkeypatch) -> None:
    from app.strategy import swing_strategy as mod

    monkeypatch.setattr(mod, "filter_quality_swing_candidates", lambda _df: ["005930"])
    strategy = SwingStrategy(
        bull_strategy=_DummyStrategy("bull_strategy"),
        bear_strategy=_DummyStrategy("bear_strategy"),
        sideways_strategy=_DummyStrategy("sideways_strategy"),
    )
    ctx = StrategyContext(
        prices=_make_prices(),
        kospi_index=_make_index(2500, 2.0),
        sp500_index=_make_index(4500, 3.0),
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]),
        volatility_index=_make_vol(18.0, rising=False),
    )
    signals = strategy.generate_signals(ctx)
    assert signals and signals[0].strategy_name == "bull_strategy"


def test_regime_switch_to_sideways_strategy(monkeypatch) -> None:
    from app.strategy import swing_strategy as mod

    monkeypatch.setattr(mod, "filter_quality_swing_candidates", lambda _df: ["005930"])
    strategy = SwingStrategy(
        bull_strategy=_DummyStrategy("bull_strategy"),
        bear_strategy=_DummyStrategy("bear_strategy"),
        sideways_strategy=_DummyStrategy("sideways_strategy"),
    )
    flat = _make_index(2500, 0.02)
    ctx = StrategyContext(
        prices=_make_prices(),
        kospi_index=flat,
        sp500_index=flat,
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]),
        volatility_index=_make_vol(16.0, rising=False),
    )
    signals = strategy.generate_signals(ctx)
    assert signals and signals[0].strategy_name == "sideways_strategy"


def test_regime_switch_to_high_volatility_blocks_new_entries(monkeypatch) -> None:
    from app.strategy import swing_strategy as mod

    monkeypatch.setattr(mod, "filter_quality_swing_candidates", lambda _df: ["005930"])
    strategy = SwingStrategy()
    ctx = StrategyContext(
        prices=_make_prices(),
        kospi_index=_make_index(2500, 2.0),
        sp500_index=_make_index(4500, 3.0),
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]),
        volatility_index=_make_vol(30.0, rising=True),
    )
    signals = strategy.generate_signals(ctx)
    assert signals == []
