from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Query

from backend.app.core.config import get_backend_settings
from backend.app.portfolio.performance_aggregate import (
    build_performance_metrics,
    filter_fill_rows,
    filter_pnl_rows,
    load_fill_rows,
    load_pnl_rows,
    replay_fills,
)
from backend.app.strategy.signal_engine import get_swing_signal_engine, snapshot_to_jsonable

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("/metrics")
def performance_metrics(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    cfg = get_backend_settings()
    return build_performance_metrics(
        cfg,
        start_date=start_date,
        end_date=end_date,
        strategy_id=strategy_id,
        symbol=symbol,
    )


@router.get("/pnl-history")
def pnl_history(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    _ = (strategy_id, symbol)
    cfg = get_backend_settings()
    rows = filter_pnl_rows(_load_pnl_rows(cfg), start_date, end_date)
    items: list[dict[str, object]] = []
    for r in rows[-400:]:
        ts = str(r.get("ts_utc") or "")
        items.append(
            {
                "date": ts[:10] if len(ts) >= 10 else ts,
                "daily_return_pct": float(r.get("daily_pnl_pct") or 0.0),
                "equity": float(r.get("equity") or 0.0),
            }
        )
    return {"items": items, "count": len(items), "data_source": "portfolio_data/pnl_history.jsonl"}


@router.get("/trade-history")
def trade_history(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    cfg = get_backend_settings()
    fills = filter_fill_rows(load_fill_rows(cfg), start_date, end_date, strategy_id, symbol)
    items, _replay = replay_fills(cfg, fills)
    return {"items": items[:500], "count": min(len(items), 500), "data_source": "portfolio_data/fills.jsonl"}


@router.get("/symbol-performance")
def symbol_performance(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    cfg = get_backend_settings()
    trades, _ = replay_fills(cfg, filter_fill_rows(load_fill_rows(cfg), start_date, end_date, strategy_id, symbol))
    by_symbol: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by_symbol[str(t["symbol"])].append(float(t["net_pnl"]))
    items: list[dict[str, object]] = []
    for sym, pnls in by_symbol.items():
        wins = sum(1 for p in pnls if p > 0)
        total = sum(pnls)
        denom = sum(abs(x) for x in pnls) or 1.0
        items.append(
            {
                "symbol": sym,
                "pnl": round(total, 4),
                "return_pct": round((total / denom) * 100.0, 4),
                "win_rate_pct": round((wins / len(pnls)) * 100.0, 4),
            }
        )
    items.sort(key=lambda x: float(x["pnl"]), reverse=True)
    return {"items": items, "count": len(items), "data_source": "fills_fifo_replay_net"}


@router.get("/strategy-performance")
def strategy_performance(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    cfg = get_backend_settings()
    trades, _ = replay_fills(cfg, filter_fill_rows(load_fill_rows(cfg), start_date, end_date, strategy_id, symbol))
    by_strategy: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by_strategy[str(t["strategy_id"])].append(float(t["net_pnl"]))
    items: list[dict[str, object]] = []
    for sid, pnls in by_strategy.items():
        wins = sum(1 for p in pnls if p > 0)
        total = sum(pnls)
        denom = sum(abs(x) for x in pnls) or 1.0
        items.append(
            {
                "strategy_id": sid,
                "pnl": round(total, 4),
                "return_pct": round((total / denom) * 100.0, 4),
                "win_rate_pct": round((wins / len(pnls)) * 100.0, 4),
            }
        )
    items.sort(key=lambda x: float(x["pnl"]), reverse=True)
    return {"items": items, "count": len(items), "data_source": "fills_fifo_replay_net"}


@router.get("/regime-performance")
def regime_performance(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    _ = (start_date, end_date, strategy_id, symbol)
    metrics = performance_metrics(start_date=start_date, end_date=end_date, strategy_id=strategy_id, symbol=symbol)
    sig_snap = get_swing_signal_engine().get_snapshot()
    regime = "unknown"
    if sig_snap is not None:
        regime = str(snapshot_to_jsonable(sig_snap).get("market_regime") or "unknown")
    total = float(metrics.get("realized_pnl") or 0.0) + float(metrics.get("unrealized_pnl") or 0.0)
    items = [
        {
            "regime": regime,
            "pnl": round(total, 4),
            "return_pct": round(float(metrics.get("cumulative_return_pct") or 0.0), 4),
            "win_rate_pct": round(float(metrics.get("win_rate_pct") or 0.0), 4),
        }
    ]
    return {"items": items, "count": 1, "data_source": "runtime_snapshot_estimated"}
