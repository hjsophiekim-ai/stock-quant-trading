from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal


class OrderStatus(StrEnum):
    CREATED = "created"
    APPROVED = "approved"
    PENDING_RISK = "pending_risk"
    REJECTED_RISK = "rejected_risk"
    REJECTED = "rejected"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class OrderRequest:
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int
    price: float | None
    stop_loss_pct: float | None = None
    strategy_id: str = "swing_strategy"
    signal_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OrderResult:
    order_id: str
    accepted: bool
    message: str
    status: OrderStatus = OrderStatus.SUBMITTED
    filled_quantity: int = 0
    avg_fill_price: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class OrderSignal:
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int
    limit_price: float | None
    stop_loss_pct: float | None
    strategy_id: str
    signal_id: str | None = None


@dataclass(frozen=True)
class OrderIntent:
    signal: OrderSignal
    approved: bool
    reason_code: str
    reason: str
