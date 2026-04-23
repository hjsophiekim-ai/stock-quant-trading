from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

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


@dataclass(frozen=True)
class AccountEquitySnapshot:
    orderable_cash: float
    cash_total: float | None
    reserved_cash_open_buys: float
    positions_market_value: float | None
    source_of_truth: str
    open_buy_order_count: int
    open_buy_order_missing_price_count: int
    reserved_cash_estimation_method: str
    raw_balance_summary: dict[str, Any]


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

    def get_account_equity_snapshot(self) -> AccountEquitySnapshot:
        raise NotImplementedError
