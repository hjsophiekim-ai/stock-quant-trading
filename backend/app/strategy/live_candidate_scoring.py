from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LiveCandidateScore:
    symbol: str
    score: float
    reason: str


def score_candidate(
    *,
    symbol: str,
    base_signal_score: float | None = None,
    order_price: float | None,
    market_mode: dict[str, Any] | None,
    already_holding: bool,
    has_open_order: bool,
    strategy_performance: dict[str, Any] | None = None,
    rr_proxy: float | None = None,
    liquidity_proxy: float | None = None,
    volatility_proxy: float | None = None,
) -> LiveCandidateScore:
    sym = str(symbol or "").strip()
    if not sym:
        return LiveCandidateScore(symbol="", score=-999.0, reason="empty_symbol")

    mode = (market_mode or {}).get("market_mode_active") if isinstance(market_mode, dict) else None
    mode = str(mode or "").strip().lower()

    score = 0.0
    parts: list[str] = []

    if base_signal_score is not None:
        b = float(base_signal_score)
        score += max(-1.2, min(1.2, b))
        parts.append(f"base_signal_score={b:.3f}")

    if mode == "aggressive":
        score += 0.8
        parts.append("mode=aggressive +0.8")
    elif mode == "defensive":
        score -= 0.9
        parts.append("mode=defensive -0.9")
    else:
        parts.append(f"mode={mode or 'neutral'} +0.0")

    if isinstance(strategy_performance, dict) and strategy_performance:
        if "score_adjustment" in strategy_performance or "buy_blocked" in strategy_performance:
            try:
                adj = float(strategy_performance.get("score_adjustment") or 0.0)
            except Exception:
                adj = 0.0
            blocked = bool(strategy_performance.get("buy_blocked"))
            if blocked:
                score -= 5.0
                parts.append("perf_buy_blocked -5.0")
            if adj:
                score += adj
                parts.append(f"perf_score_adj={adj:+.3f}")
            r = str(strategy_performance.get("reason") or "")
            if r:
                parts.append(f"perf_reason={r}")
        else:
            dq = strategy_performance.get("data_quality") if isinstance(strategy_performance.get("data_quality"), dict) else {}
            trades = int(dq.get("sell_trades_count") or 0)
            win = float(strategy_performance.get("win_rate_pct") or 0.0)
            payoff = float(strategy_performance.get("payoff_ratio") or 0.0)
            net = float(strategy_performance.get("net_realized_pnl") or 0.0)
            if trades >= 10 and win >= 55.0 and payoff >= 1.2:
                score += 0.8
                parts.append(f"perf_bonus trades={trades} win={win:.1f} payoff={payoff:.2f} +0.8")
            elif trades >= 10 and win < 40.0 and payoff < 1.0:
                score -= 0.8
                parts.append(f"perf_penalty trades={trades} win={win:.1f} payoff={payoff:.2f} -0.8")
            if net < 0:
                score -= 0.2
                parts.append("perf_net_realized_pnl_negative -0.2")
            elif net > 0:
                score += 0.1
                parts.append("perf_net_realized_pnl_positive +0.1")

    if already_holding:
        score -= 2.5
        parts.append("already_holding -2.5")
    if has_open_order:
        score -= 3.5
        parts.append("duplicate_open_order -3.5")

    if rr_proxy is not None:
        rr = float(rr_proxy)
        score += max(-1.0, min(1.2, rr - 1.0))
        parts.append(f"rr_proxy={rr:.2f}")
    if liquidity_proxy is not None:
        liq = float(liquidity_proxy)
        score += max(-0.8, min(0.8, liq))
        parts.append(f"liquidity={liq:.2f}")
    if volatility_proxy is not None:
        vol = float(volatility_proxy)
        score -= max(0.0, min(1.2, vol))
        parts.append(f"volatility_penalty={vol:.2f}")

    if order_price is None or float(order_price or 0.0) <= 0:
        score -= 0.4
        parts.append("missing_price -0.4")

    return LiveCandidateScore(symbol=sym, score=float(score), reason="; ".join(parts)[:600])

