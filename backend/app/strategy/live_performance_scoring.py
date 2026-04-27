from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.core.config import BackendSettings
from backend.app.portfolio.performance_aggregate import filter_fill_rows, load_fill_rows, replay_fills


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _start_date_iso(lookback_days: int) -> str:
    d = datetime.now(timezone.utc).date() - timedelta(days=max(1, int(lookback_days or 1)))
    return d.isoformat()


def _drawdown_pct(series: list[float]) -> float:
    peak = None
    mdd = 0.0
    for x in series:
        if peak is None or x > peak:
            peak = x
        if peak and peak != 0:
            dd = (x - peak) / peak * 100.0
            if dd < mdd:
                mdd = dd
    return float(abs(mdd))


def _daily_key_from_filled_at(s: str) -> str:
    if not s:
        return ""
    if len(s) >= 8 and s[:8].isdigit():
        return s[:8]
    return ""


@dataclass(frozen=True)
class PerformanceSignal:
    score_adjustment: float
    buy_blocked: bool
    reason: str
    metrics: dict[str, Any]


_cache: dict[str, tuple[float, PerformanceSignal]] = {}


def get_performance_signal(
    cfg: BackendSettings,
    *,
    strategy_id: str,
    symbol: str | None = None,
    lookback_days: int = 60,
    min_sell_trades: int = 10,
    cache_ttl_sec: float = 45.0,
) -> PerformanceSignal:
    sid = str(strategy_id or "").strip() or "unknown"
    sym = str(symbol or "").strip()
    cache_key = f"{sid}|{sym}|{int(lookback_days)}|{int(min_sell_trades)}"
    now = datetime.now(timezone.utc).timestamp()
    hit = _cache.get(cache_key)
    if hit and (now - float(hit[0])) < float(cache_ttl_sec):
        return hit[1]

    start_date = _start_date_iso(lookback_days)
    fills = load_fill_rows(cfg, limit=20000)
    fills = filter_fill_rows(fills, start_date=start_date, end_date=None, strategy_id=sid, symbol=(sym or None))
    trades, replay = replay_fills(cfg, fills)

    sell_trades = [t for t in trades if float(t.get("net_pnl") or 0.0) != 0.0]
    wins = [t for t in sell_trades if float(t.get("net_pnl") or 0.0) > 0]
    losses = [t for t in sell_trades if float(t.get("net_pnl") or 0.0) < 0]
    win_rate = (len(wins) / len(sell_trades) * 100.0) if sell_trades else 0.0
    sum_win = sum(float(t.get("net_pnl") or 0.0) for t in wins)
    sum_loss_abs = abs(sum(float(t.get("net_pnl") or 0.0) for t in losses))
    profit_factor = (sum_win / sum_loss_abs) if sum_loss_abs > 0 else (999.0 if sum_win > 0 else 0.0)
    avg_win = (sum_win / len(wins)) if wins else 0.0
    avg_loss = (sum_loss_abs / len(losses)) if losses else 0.0

    daily_net: dict[str, float] = {}
    for t in trades:
        k = _daily_key_from_filled_at(str(t.get("filled_at") or ""))
        if not k:
            continue
        daily_net[k] = float(daily_net.get(k, 0.0)) + float(t.get("net_pnl") or 0.0)
    days = sorted(daily_net.keys())
    recent_days = days[-5:]
    recent_net_krw = sum(float(daily_net.get(d, 0.0)) for d in recent_days) if recent_days else 0.0

    cum: list[float] = []
    c = 0.0
    for t in sell_trades:
        c += float(t.get("net_pnl") or 0.0)
        cum.append(c)
    mdd_proxy_pct = _drawdown_pct([x + 1_000_000.0 for x in cum]) if cum else 0.0

    trade_count = int(len(sell_trades))
    sample_ok = trade_count >= int(min_sell_trades)

    score_adj = 0.0
    blocked = False
    parts: list[str] = []
    parts.append(f"sid={sid}")
    if sym:
        parts.append(f"sym={sym}")
    parts.append(f"trades={trade_count} sample_ok={sample_ok}")

    if not sample_ok:
        parts.append("insufficient_samples")
    else:
        if profit_factor >= 1.3 and win_rate >= 55.0:
            score_adj += 0.8
            parts.append(f"good_pf_win +0.8 pf={profit_factor:.2f} win={win_rate:.1f}")
        elif profit_factor < 1.0 and recent_net_krw < 0:
            score_adj -= 0.8
            parts.append(f"bad_pf_recent -0.8 pf={profit_factor:.2f} recent5d={recent_net_krw:.0f}")
        if profit_factor < 0.85 and recent_net_krw < 0:
            blocked = True
            parts.append("buy_blocked_due_to_bad_performance")
        if mdd_proxy_pct >= 8.0:
            score_adj -= 0.4
            parts.append(f"dd_penalty -0.4 mdd_proxy_pct={mdd_proxy_pct:.2f}")

    sig = PerformanceSignal(
        score_adjustment=float(score_adj),
        buy_blocked=bool(blocked),
        reason="; ".join(parts)[:700],
        metrics={
            "strategy_id": sid,
            "symbol": sym or None,
            "start_date": start_date,
            "end_date": _utc_today_iso(),
            "trade_count": trade_count,
            "win_rate_pct": float(round(win_rate, 4)),
            "avg_win_krw": float(round(avg_win, 4)),
            "avg_loss_krw": float(round(avg_loss, 4)),
            "profit_factor": float(round(profit_factor, 4)),
            "recent_5d_net_pnl_krw": float(round(recent_net_krw, 4)),
            "max_drawdown_proxy_pct": float(round(mdd_proxy_pct, 4)),
            "net_realized_pnl_krw": float(replay.net_realized_pnl),
            "fills_used": int(len(fills)),
            "sell_trades_count": trade_count,
            "sample_ok": bool(sample_ok),
        },
    )
    _cache[cache_key] = (now, sig)
    return sig

