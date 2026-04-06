from dataclasses import dataclass


@dataclass(frozen=True)
class PositionSizingPlan:
    quantity: int
    target_value: float
    target_weight: float
    reason: str


def fixed_fraction_size(cash: float, risk_fraction: float, entry_price: float) -> int:
    if cash <= 0 or risk_fraction <= 0 or entry_price <= 0:
        return 0
    budget = cash * risk_fraction
    return int(budget // entry_price)


def size_position_by_weight(
    *,
    equity: float,
    entry_price: float,
    min_weight: float = 0.10,
    max_weight: float = 0.15,
    prefer_weight: float = 0.12,
) -> PositionSizingPlan:
    if equity <= 0:
        return PositionSizingPlan(quantity=0, target_value=0.0, target_weight=0.0, reason="Invalid equity")
    if entry_price <= 0:
        return PositionSizingPlan(quantity=0, target_value=0.0, target_weight=0.0, reason="Invalid entry price")
    if not (0 < min_weight <= prefer_weight <= max_weight):
        return PositionSizingPlan(quantity=0, target_value=0.0, target_weight=0.0, reason="Invalid weight setup")

    target_value = equity * prefer_weight
    qty = int(target_value // entry_price)
    if qty <= 0:
        return PositionSizingPlan(quantity=0, target_value=target_value, target_weight=prefer_weight, reason="Too small equity for 1 share")

    actual_weight = (qty * entry_price) / equity
    if actual_weight < min_weight:
        min_qty = int((equity * min_weight) // entry_price)
        if min_qty <= 0:
            return PositionSizingPlan(quantity=0, target_value=target_value, target_weight=prefer_weight, reason="Cannot satisfy min weight")
        qty = min_qty
        actual_weight = (qty * entry_price) / equity

    if actual_weight > max_weight:
        max_qty = int((equity * max_weight) // entry_price)
        qty = max(max_qty, 0)
        actual_weight = (qty * entry_price) / equity if qty > 0 else 0.0

    return PositionSizingPlan(
        quantity=qty,
        target_value=qty * entry_price,
        target_weight=actual_weight,
        reason="Sized by 10-15% position weight policy",
    )
