from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Position:
    symbol: str
    quantity: int
    average_price: float
    initial_quantity: int | None = None
    realized_sell_quantity: int = 0
    first_take_profit_done: bool = False
    trailing_active: bool = False
    highest_price_since_entry: float | None = None


def calculate_new_average_price(
    current_qty: int,
    current_avg_price: float,
    buy_qty: int,
    buy_price: float,
) -> float:
    if current_qty < 0 or buy_qty <= 0:
        raise ValueError("Invalid quantity for average price calculation")
    if current_avg_price < 0 or buy_price <= 0:
        raise ValueError("Invalid price for average price calculation")
    total_qty = current_qty + buy_qty
    if total_qty == 0:
        return 0.0
    total_cost = (current_qty * current_avg_price) + (buy_qty * buy_price)
    return total_cost / total_qty


def apply_buy_fill(position: Position | None, quantity: int, fill_price: float, symbol: str) -> Position:
    if quantity <= 0 or fill_price <= 0:
        raise ValueError("Buy fill must have positive quantity and price")
    if position is None:
        return Position(
            symbol=symbol,
            quantity=quantity,
            average_price=fill_price,
            initial_quantity=quantity,
            realized_sell_quantity=0,
            first_take_profit_done=False,
            trailing_active=False,
            highest_price_since_entry=fill_price,
        )
    new_avg = calculate_new_average_price(position.quantity, position.average_price, quantity, fill_price)
    init_qty = position.initial_quantity if position.initial_quantity is not None else position.quantity
    return Position(
        symbol=position.symbol,
        quantity=position.quantity + quantity,
        average_price=new_avg,
        initial_quantity=init_qty + quantity,
        realized_sell_quantity=position.realized_sell_quantity,
        first_take_profit_done=position.first_take_profit_done,
        trailing_active=position.trailing_active,
        highest_price_since_entry=max(position.highest_price_since_entry or fill_price, fill_price),
    )


def apply_sell_fill(position: Position, quantity: int, *, mark_first_take_profit: bool = False) -> Position | None:
    if quantity <= 0:
        raise ValueError("Sell fill must have positive quantity")
    if quantity > position.quantity:
        raise ValueError("Sell quantity exceeds current position")
    remain = position.quantity - quantity
    if remain == 0:
        return None
    init_qty = position.initial_quantity if position.initial_quantity is not None else position.quantity
    realized = position.realized_sell_quantity + quantity
    first_tp_done = position.first_take_profit_done or mark_first_take_profit or (realized >= max(int(init_qty * 0.5), 1))
    return Position(
        symbol=position.symbol,
        quantity=remain,
        average_price=position.average_price,
        initial_quantity=init_qty,
        realized_sell_quantity=realized,
        first_take_profit_done=first_tp_done,
        trailing_active=first_tp_done,
        highest_price_since_entry=position.highest_price_since_entry,
    )


def update_high_watermark(position: Position, latest_price: float) -> Position:
    if latest_price <= 0:
        return position
    high = max(position.highest_price_since_entry or latest_price, latest_price)
    return Position(
        symbol=position.symbol,
        quantity=position.quantity,
        average_price=position.average_price,
        initial_quantity=position.initial_quantity,
        realized_sell_quantity=position.realized_sell_quantity,
        first_take_profit_done=position.first_take_profit_done,
        trailing_active=position.trailing_active,
        highest_price_since_entry=high,
    )
