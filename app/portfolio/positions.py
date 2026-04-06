from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Position:
    symbol: str
    quantity: int
    average_price: float


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
        return Position(symbol=symbol, quantity=quantity, average_price=fill_price)
    new_avg = calculate_new_average_price(position.quantity, position.average_price, quantity, fill_price)
    return Position(symbol=position.symbol, quantity=position.quantity + quantity, average_price=new_avg)


def apply_sell_fill(position: Position, quantity: int) -> Position | None:
    if quantity <= 0:
        raise ValueError("Sell fill must have positive quantity")
    if quantity > position.quantity:
        raise ValueError("Sell quantity exceeds current position")
    remain = position.quantity - quantity
    if remain == 0:
        return None
    return Position(symbol=position.symbol, quantity=remain, average_price=position.average_price)
