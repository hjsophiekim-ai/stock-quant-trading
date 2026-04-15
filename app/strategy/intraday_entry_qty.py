"""인트라데이 스캘프 매수 수량: 고정 vs 리스크·버킷 기반."""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.strategy.paper_position_sizing import compute_intraday_buy_quantity


def resolved_intraday_entry_quantity(
    cfg: Settings,
    strategy_self: Any,
    *,
    price_krw: float,
    stop_loss_pct_points: float,
) -> int:
    if not cfg.paper_uses_intraday_risk_sized_quantity:
        return max(1, int(cfg.paper_intraday_order_quantity))
    eq = float(getattr(strategy_self, "_router_equity_krw", 0.0) or 0.0)
    bud = float(getattr(strategy_self, "_router_intraday_budget_krw", 0.0) or 0.0)
    return compute_intraday_buy_quantity(
        price_krw=float(price_krw),
        stop_loss_pct_points=float(stop_loss_pct_points),
        equity_krw=eq,
        intraday_budget_krw=bud,
        max_position_pct=float(cfg.paper_max_capital_per_position_pct),
        risk_per_trade_pct=float(cfg.paper_risk_per_trade_pct),
        fallback_qty=max(1, int(cfg.paper_intraday_order_quantity)),
    )
