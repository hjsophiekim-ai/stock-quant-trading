from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.orders.models import OrderRequest, OrderResult


@dataclass(frozen=True)
class PositionView:
    symbol: str
    quantity: int
    average_price: float


@dataclass(frozen=True)
class OpenOrder:
    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int
    remaining_quantity: int
    price: float | None
    created_at: datetime


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int
    fill_price: float
    filled_at: datetime


class BaseBroker(ABC):
    @abstractmethod
    def get_cash(self) -> float:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> list[PositionView]:
        raise NotImplementedError

    @abstractmethod
    def place_order(self, order: OrderRequest) -> OrderResult:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> OrderResult:
        raise NotImplementedError

    @abstractmethod
    def get_open_orders(self) -> list[OpenOrder]:
        raise NotImplementedError

    @abstractmethod
    def get_fills(self) -> list[Fill]:
        raise NotImplementedError
