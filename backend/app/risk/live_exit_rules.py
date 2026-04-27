from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class ExitDecision:
    should_sell: bool
    symbol: str
    quantity: int
    reason: str
    order_type: str = "market"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def should_skip_due_to_cooldown(*, cooldown_until_utc: str | None) -> tuple[bool, str]:
    if not cooldown_until_utc:
        return False, ""
    try:
        until = datetime.fromisoformat(str(cooldown_until_utc))
    except Exception:
        return False, ""
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if _now_utc() < until:
        return True, f"cooldown_active until={until.isoformat()}"
    return False, ""


def evaluate_exit_for_position(
    *,
    symbol: str,
    quantity: int,
    average_price: float,
    last_price: float,
    state: dict[str, Any],
    stop_loss_enabled: bool,
    take_profit_enabled: bool,
    trailing_enabled: bool,
    stop_loss_pct: float = 0.015,
    take_profit_pct: float = 0.025,
    trailing_start_profit_pct: float = 0.02,
    trailing_gap_pct: float = 0.012,
) -> ExitDecision:
    sym = str(symbol or "").strip()
    q = int(quantity or 0)
    avg = float(average_price or 0.0)
    px = float(last_price or 0.0)
    if not sym or q <= 0 or avg <= 0 or px <= 0:
        return ExitDecision(should_sell=False, symbol=sym, quantity=0, reason="invalid_position")

    pnl_pct = (px / avg) - 1.0

    if stop_loss_enabled and pnl_pct <= -abs(float(stop_loss_pct)):
        return ExitDecision(
            should_sell=True,
            symbol=sym,
            quantity=q,
            reason=f"stop_loss pnl_pct={pnl_pct:.4f} avg={avg:.2f} last={px:.2f}",
        )

    if take_profit_enabled and pnl_pct >= abs(float(take_profit_pct)):
        return ExitDecision(
            should_sell=True,
            symbol=sym,
            quantity=q,
            reason=f"take_profit pnl_pct={pnl_pct:.4f} avg={avg:.2f} last={px:.2f}",
        )

    if trailing_enabled:
        trail = state.get("trailing") if isinstance(state.get("trailing"), dict) else {}
        sym_tr = trail.get(sym) if isinstance(trail.get(sym), dict) else {}
        hi = float(sym_tr.get("highest") or 0.0)
        if px > hi:
            hi = px
            sym_tr = {**sym_tr, "highest": hi, "updated_at_utc": _now_utc().isoformat()}
            trail = {**trail, sym: sym_tr}
            state["trailing"] = trail
        if hi > 0 and (hi / avg - 1.0) >= abs(float(trailing_start_profit_pct)):
            dd = (px / hi) - 1.0
            if dd <= -abs(float(trailing_gap_pct)):
                return ExitDecision(
                    should_sell=True,
                    symbol=sym,
                    quantity=q,
                    reason=f"trailing_stop dd={dd:.4f} hi={hi:.2f} avg={avg:.2f} last={px:.2f}",
                )

    return ExitDecision(should_sell=False, symbol=sym, quantity=0, reason="hold")


def set_cooldown_after_loss(*, state: dict[str, Any], minutes: int) -> str | None:
    mins = max(0, int(minutes or 0))
    if mins <= 0:
        return None
    until = _now_utc() + timedelta(minutes=mins)
    state["cooldown_until_utc"] = until.isoformat()
    return state["cooldown_until_utc"]

