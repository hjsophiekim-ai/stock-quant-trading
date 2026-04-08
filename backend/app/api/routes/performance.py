from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from backend.app.core.config import get_backend_settings
from backend.app.portfolio.sync_engine import load_last_snapshot, read_jsonl_tail
from backend.app.strategy.signal_engine import get_swing_signal_engine, snapshot_to_jsonable

router = APIRouter(prefix="/performance", tags=["performance"])


def _parse_date(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _load_pnl_rows(limit: int = 5000) -> list[dict[str, Any]]:
    cfg = get_backend_settings()
    p = Path(cfg.portfolio_data_dir) / "pnl_history.jsonl"
    return read_jsonl_tail(p, max_lines=limit)


def _load_fill_rows(limit: int = 20000) -> list[dict[str, Any]]:
    cfg = get_backend_settings()
    p = Path(cfg.portfolio_data_dir) / "fills.jsonl"
    return read_jsonl_tail(p, max_lines=limit)


def _fill_dt(row: dict[str, Any]) -> datetime | None:
    odt = str(row.get("ord_dt") or "")
    otm = str(row.get("ord_tmd") or "").ljust(6, "0")[:6]
    if len(odt) != 8:
        return None
    try:
        return datetime.strptime(odt + otm, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _pnl_ts(row: dict[str, Any]) -> datetime | None:
    ts = row.get("ts_utc")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _filter_pnl_rows(rows: list[dict[str, Any]], start_date: str | None, end_date: str | None) -> list[dict[str, Any]]:
    s = _parse_date(start_date)
    e = _parse_date(end_date)
    out: list[dict[str, Any]] = []
    for r in rows:
        dt = _pnl_ts(r)
        if dt is None:
            continue
        if s and dt < s:
            continue
        if e and dt > e:
            continue
        out.append(r)
    return out


def _filter_fill_rows(
    rows: list[dict[str, Any]],
    start_date: str | None,
    end_date: str | None,
    strategy_id: str | None,
    symbol: str | None,
) -> list[dict[str, Any]]:
    s = _parse_date(start_date)
    e = _parse_date(end_date)
    sid = (strategy_id or "").strip()
    sym = (symbol or "").strip()
    out: list[dict[str, Any]] = []
    for r in rows:
        dt = _fill_dt(r)
        if dt is None:
            continue
        if s and dt < s:
            continue
        if e and dt > e:
            continue
        if sid and str(r.get("strategy_id") or "") != sid:
            continue
        if sym and str(r.get("symbol") or "") != sym:
            continue
        out.append(r)
    out.sort(key=lambda x: (str(x.get("ord_dt") or ""), str(x.get("ord_tmd") or ""), str(x.get("exec_id") or "")))
    return out


def _rolling_max_drawdown_pct(equities: list[float]) -> float:
    if not equities:
        return 0.0
    peak = equities[0]
    worst = 0.0
    for e in equities:
        if e > peak:
            peak = e
        if peak > 0:
            dd = ((e / peak) - 1.0) * 100.0
            if dd < worst:
                worst = dd
    return round(worst, 4)


def _compute_trade_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    단순 평균단가 기반 체결 리플레이로 sell 체결마다 realized pnl 추정.
    TODO: 포지션 엔진과 동일한 정밀 FIFO/수수료 반영으로 고도화.
    """
    qty_by_symbol: dict[str, int] = defaultdict(int)
    avg_by_symbol: dict[str, float] = defaultdict(float)
    out: list[dict[str, Any]] = []
    idx = 0
    for r in rows:
        side = str(r.get("side") or "").lower()
        sym = str(r.get("symbol") or "")
        sid = str(r.get("strategy_id") or "unknown")
        qty = int(r.get("quantity") or 0)
        px = float(r.get("price") or 0.0)
        if not sym or qty <= 0 or px <= 0:
            continue
        if side == "buy":
            old_q = qty_by_symbol[sym]
            old_avg = avg_by_symbol[sym]
            new_q = old_q + qty
            new_avg = ((old_avg * old_q) + (px * qty)) / new_q if new_q > 0 else 0.0
            qty_by_symbol[sym] = new_q
            avg_by_symbol[sym] = new_avg
            continue
        if side != "sell":
            continue
        base_q = qty_by_symbol[sym]
        base_avg = avg_by_symbol[sym]
        eff_qty = min(base_q, qty) if base_q > 0 else qty
        pnl = (px - base_avg) * eff_qty if base_q > 0 else 0.0
        qty_by_symbol[sym] = max(base_q - qty, 0)
        result = "win" if pnl > 0 else "loss" if pnl < 0 else "flat"
        idx += 1
        out.append(
            {
                "trade_id": str(r.get("exec_id") or f"fill-{idx}"),
                "symbol": sym,
                "strategy_id": sid,
                "pnl": round(pnl, 4),
                "result": result,
                "quantity": qty,
                "price": px,
                "filled_at": f"{r.get('ord_dt','')}{str(r.get('ord_tmd','')).ljust(6,'0')[:6]}",
            }
        )
    out.reverse()
    return out


@router.get("/metrics")
def performance_metrics(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    snap = load_last_snapshot() or {}
    pnl_rows = _filter_pnl_rows(_load_pnl_rows(), start_date, end_date)
    fill_rows = _filter_fill_rows(_load_fill_rows(), start_date, end_date, strategy_id, symbol)
    trades = _compute_trade_rows(fill_rows)

    daily = float(snap.get("daily_pnl_pct") or 0.0)
    cumulative = float(snap.get("cumulative_pnl_pct") or 0.0)
    monthly = 0.0
    weekly = 0.0
    if len(pnl_rows) >= 2:
        latest_eq = float(pnl_rows[-1].get("equity") or 0.0)
        week_anchor = float(pnl_rows[max(0, len(pnl_rows) - 6)].get("equity") or 0.0)
        if latest_eq > 0 and week_anchor > 0:
            weekly = ((latest_eq / week_anchor) - 1.0) * 100.0
        this_month = datetime.now().strftime("%Y-%m")
        month_rows = [r for r in pnl_rows if str(r.get("ts_utc") or "").startswith(this_month)]
        if month_rows:
            m0 = float(month_rows[0].get("equity") or 0.0)
            if latest_eq > 0 and m0 > 0:
                monthly = ((latest_eq / m0) - 1.0) * 100.0

    wins = [t for t in trades if float(t.get("pnl") or 0.0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0.0) < 0]
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    avg_win = sum(float(t["pnl"]) for t in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(float(t["pnl"]) for t in losses) / len(losses)) if losses else 0.0
    payoff = (avg_win / avg_loss) if avg_loss > 0 else (1.0 if avg_win > 0 else 0.0)
    mdd = _rolling_max_drawdown_pct([float(r.get("equity") or 0.0) for r in pnl_rows if float(r.get("equity") or 0.0) > 0])

    return {
        "daily_return_pct": round(daily, 4),
        "weekly_return_pct": round(weekly, 4),
        "monthly_return_pct": round(monthly, 4),
        "cumulative_return_pct": round(cumulative, 4),
        "realized_pnl": float(snap.get("realized_pnl") or 0.0),
        "unrealized_pnl": float(snap.get("unrealized_pnl") or 0.0),
        "max_drawdown_pct": mdd,
        "win_rate_pct": round(win_rate, 4),
        "payoff_ratio": round(payoff, 4),
        "data_source": "portfolio_sync_snapshot",
        "value_sources": {
            "daily_return_pct": "portfolio_snapshot.daily_pnl_pct",
            "weekly_return_pct": "derived_from_pnl_history_last_6_points_equity",
            "monthly_return_pct": "derived_from_pnl_history_month_start_to_latest_equity",
            "cumulative_return_pct": "portfolio_snapshot.cumulative_pnl_pct",
            "realized_pnl": "portfolio_snapshot.realized_pnl",
            "unrealized_pnl": "portfolio_snapshot.unrealized_pnl",
            "max_drawdown_pct": "derived_from_pnl_history_equity_curve",
            "win_rate_pct": "fills_replay_sell_trade_rows",
            "payoff_ratio": "fills_replay_sell_trade_rows",
        },
        "data_quality": {
            "win_rate_and_payoff_estimated": True,
            "fees_and_tax_included_in_trade_replay": False,
            "monthly_return_estimated": True,
        },
    }


@router.get("/pnl-history")
def pnl_history(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    _ = (strategy_id, symbol)  # pnl_history는 전체 계좌 equity 기준
    rows = _filter_pnl_rows(_load_pnl_rows(), start_date, end_date)
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
    fills = _filter_fill_rows(_load_fill_rows(), start_date, end_date, strategy_id, symbol)
    items = _compute_trade_rows(fills)[:500]
    return {"items": items, "count": len(items), "data_source": "portfolio_data/fills.jsonl"}


@router.get("/symbol-performance")
def symbol_performance(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    trades = _compute_trade_rows(_filter_fill_rows(_load_fill_rows(), start_date, end_date, strategy_id, symbol))
    by_symbol: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by_symbol[str(t["symbol"])].append(float(t["pnl"]))
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
    return {"items": items, "count": len(items), "data_source": "fills_replay"}


@router.get("/strategy-performance")
def strategy_performance(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    trades = _compute_trade_rows(_filter_fill_rows(_load_fill_rows(), start_date, end_date, strategy_id, symbol))
    by_strategy: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by_strategy[str(t["strategy_id"])].append(float(t["pnl"]))
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
    return {"items": items, "count": len(items), "data_source": "fills_replay"}


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
