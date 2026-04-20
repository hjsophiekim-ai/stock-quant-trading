"""종가베팅(final_betting_v1) Paper 틱 — 인트라데이 파이프라인 재사용, scalp 장마감 강제청산과 분리."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.orders.models import OrderRequest, OrderResult
from app.scheduler.intraday_jobs import IntradaySchedulerJobs


class FinalBettingIntradayJobs(IntradaySchedulerJobs):
    """주문 체결 시 final_betting_carry 동기화(overnight 메타·분할청산 잔량)."""

    def _intraday_buy_gate(self, symbol: str, state: Any, cfg: Any) -> dict[str, Any]:
        """스캘프보다 긴 중복 매수 방지(종가 짧은 창·재진입 억제)."""
        now_m = time.monotonic()
        dup = max(180.0, float(getattr(cfg, "paper_intraday_duplicate_order_guard_sec", 45.0)))
        last = float(state.last_buy_mono.get(symbol, 0.0))
        if dup > 0 and last > 0 and (now_m - last) < dup:
            return {"ok": False, "reason": "duplicate_order_guard"}
        cd_iso = state.cooldown_until_iso.get(symbol)
        if cd_iso:
            try:
                cd = datetime.fromisoformat(cd_iso.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < cd:
                    return {"ok": False, "reason": "cooldown"}
            except ValueError:
                pass
        return {"ok": True, "reason": ""}

    def _on_accepted_order(
        self, order: OrderRequest, state: Any, cfg: Any, *, fill_result: OrderResult | None = None
    ) -> None:
        super()._on_accepted_order(order, state, cfg, fill_result=fill_result)
        if order.side == "buy":
            hook = getattr(self.strategy, "consume_pending_carry_update", None)
            if not callable(hook):
                return
            meta = hook(order.symbol)
            if not meta:
                return
            carry = state.final_betting_carry
            pos = carry.setdefault("positions", {})
            pos[order.symbol] = meta
            entered = carry.setdefault("entered_symbols_today", [])
            if order.symbol not in entered:
                entered.append(order.symbol)
            return
        if order.side == "sell":
            hook = getattr(self.strategy, "on_fb_sell_accepted", None)
            if callable(hook):
                hook(
                    order.symbol,
                    int(order.quantity or 0),
                    state,
                    order=order,
                    fill_result=fill_result,
                )
