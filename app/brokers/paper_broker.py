from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from app.brokers.base_broker import AccountEquitySnapshot, BaseBroker, Fill, OpenOrder, PositionView
from app.orders.models import OrderRequest, OrderResult, OrderStatus


@dataclass
class PaperBroker(BaseBroker):
    initial_cash: float = 10_000_000.0
    price_provider: Callable[[str], float] = lambda _symbol: 50_000.0
    _cash: float = field(init=False)
    _positions: dict[str, PositionView] = field(init=False, default_factory=dict)
    _open_orders: dict[str, OpenOrder] = field(init=False, default_factory=dict)
    _fills: list[Fill] = field(init=False, default_factory=list)
    _order_seq: int = field(init=False, default=0)
    _fill_seq: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self._cash = float(self.initial_cash)

    def get_cash(self) -> float:
        return self._cash

    def get_account_equity_snapshot(self) -> AccountEquitySnapshot:
        return AccountEquitySnapshot(
            orderable_cash=float(self._cash),
            cash_total=float(self._cash),
            reserved_cash_open_buys=0.0,
            positions_market_value=None,
            source_of_truth="paper",
            open_buy_order_count=0,
            open_buy_order_missing_price_count=0,
            reserved_cash_estimation_method="none",
            raw_balance_summary={},
        )

    def get_positions(self) -> list[PositionView]:
        return list(self._positions.values())

    def place_order(self, order: OrderRequest) -> OrderResult:
        if order.quantity <= 0:
            return OrderResult(order_id="", accepted=False, message="Quantity must be positive")

        self._order_seq += 1
        order_id = f"paper-{self._order_seq:08d}"
        now = datetime.now(timezone.utc)
        open_order = OpenOrder(
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            remaining_quantity=order.quantity,
            price=order.price,
            created_at=now,
        )
        self._open_orders[order_id] = open_order

        fill_price = float(order.price) if order.price is not None else float(self.price_provider(order.symbol))
        if order.side == "buy":
            required = fill_price * order.quantity
            if required > self._cash:
                self._open_orders.pop(order_id, None)
                return OrderResult(order_id=order_id, accepted=False, message="Insufficient paper cash")
            self._cash -= required
            self._apply_buy_fill(symbol=order.symbol, quantity=order.quantity, fill_price=fill_price)
        else:
            current = self._positions.get(order.symbol)
            if current is None or current.quantity < order.quantity:
                self._open_orders.pop(order_id, None)
                return OrderResult(order_id=order_id, accepted=False, message="Insufficient paper position")
            self._cash += fill_price * order.quantity
            self._apply_sell_fill(symbol=order.symbol, quantity=order.quantity)

        self._fill_seq += 1
        fill = Fill(
            fill_id=f"paper-fill-{self._fill_seq:08d}",
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=fill_price,
            filled_at=now,
        )
        self._fills.append(fill)
        self._open_orders.pop(order_id, None)
        return OrderResult(
            order_id=order_id,
            accepted=True,
            message="Paper order filled",
            status=OrderStatus.FILLED,
            filled_quantity=int(order.quantity),
            avg_fill_price=float(fill_price),
        )

    def cancel_order(self, order_id: str) -> OrderResult:
        existed = self._open_orders.pop(order_id, None)
        if existed is None:
            return OrderResult(order_id=order_id, accepted=False, message="Order not found or already filled")
        return OrderResult(order_id=order_id, accepted=True, message="Paper order canceled")

    def get_open_orders(self) -> list[OpenOrder]:
        return list(self._open_orders.values())

    def get_fills(self) -> list[Fill]:
        return list(self._fills)

    def _apply_buy_fill(self, symbol: str, quantity: int, fill_price: float) -> None:
        previous = self._positions.get(symbol)
        if previous is None:
            self._positions[symbol] = PositionView(symbol=symbol, quantity=quantity, average_price=fill_price)
            return
        total_qty = previous.quantity + quantity
        weighted_avg = ((previous.average_price * previous.quantity) + (fill_price * quantity)) / total_qty
        self._positions[symbol] = PositionView(symbol=symbol, quantity=total_qty, average_price=weighted_avg)

    def _apply_sell_fill(self, symbol: str, quantity: int) -> None:
        previous = self._positions[symbol]
        remaining = previous.quantity - quantity
        if remaining <= 0:
            self._positions.pop(symbol, None)
            return
        self._positions[symbol] = PositionView(symbol=symbol, quantity=remaining, average_price=previous.average_price)
