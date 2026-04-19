from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from app.orders.models import OrderRequest

SignalSide = Literal["buy", "sell"]


@dataclass(frozen=True)
class StrategyContext:
    prices: pd.DataFrame
    kospi_index: pd.DataFrame
    sp500_index: pd.DataFrame
    portfolio: pd.DataFrame
    volatility_index: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["date", "value"]))


@dataclass(frozen=True)
class StrategySignal:
    symbol: str
    side: SignalSide
    quantity: int
    price: float | None
    stop_loss_pct: float | None
    reason: str
    strategy_name: str


class BaseStrategy(ABC):
    @abstractmethod
    def generate_signals(self, context: StrategyContext) -> list[StrategySignal]:
        raise NotImplementedError

    def generate_orders(self, context: StrategyContext) -> list[OrderRequest]:
        return [
            OrderRequest(
                symbol=s.symbol,
                side=s.side,
                quantity=s.quantity,
                price=s.price,
                stop_loss_pct=s.stop_loss_pct,
                strategy_id=s.strategy_name,
                signal_reason=s.reason,
            )
            for s in self.generate_signals(context)
        ]
