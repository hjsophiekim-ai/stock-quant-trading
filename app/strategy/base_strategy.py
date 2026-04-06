from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

from app.orders.models import OrderRequest


@dataclass(frozen=True)
class StrategyContext:
    prices: pd.DataFrame
    kospi_index: pd.DataFrame
    sp500_index: pd.DataFrame
    portfolio: pd.DataFrame


class BaseStrategy(ABC):
    @abstractmethod
    def generate_orders(self, context: StrategyContext) -> list[OrderRequest]:
        raise NotImplementedError
