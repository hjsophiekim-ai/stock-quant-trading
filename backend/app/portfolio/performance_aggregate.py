"""
대시보드·/api/performance 공통 집계 (동일 기준 손익·수익률).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.core.config import BackendSettings, get_backend_settings
from backend.app.portfolio.performance_math import (
    compute_equity_returns,
    fifo_and_avg_cost_replay,
    fifo_trade_rows_as_dicts,
    sort_pnl_rows_by_ts,
)
from backend.app.portfolio.sync_engine import load_last_snapshot, read_jsonl_tail


def _parse_date(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def load_pnl_rows(cfg: BackendSettings, limit: int = 5000) -> list[dict[str, Any]]:
    p = Path(cfg.portfolio_data_dir) / "pnl_history.jsonl"
    return read_jsonl_tail(p, max_lines=limit)


def load_fill_rows(cfg: BackendSettings, limit: int = 20000) -> list[dict[str, Any]]:
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


def filter_pnl_rows(
    rows: list[dict[str, Any]],
    start_date: str | None,
    end_date: str | None,
) -> list[dict[str, Any]]:
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
    return sort_pnl_rows_by_ts(out)


def filter_fill_rows(
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


def replay_fills(cfg: BackendSettings, fills: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Any]:
    replay = fifo_and_avg_cost_replay(
        fills,
        buy_fee_rate=cfg.kis_buy_fee_rate,
        sell_fee_rate=cfg.kis_sell_fee_rate,
        sell_tax_rate=cfg.krx_sell_tax_rate,
    )
    return fifo_trade_rows_as_dicts(replay), replay


_DISPLAY_LABELS_KO: dict[str, dict[str, str]] = {
    "daily_return_pct": {
        "label": "오늘 손익률",
        "hint": "pnl_history 마지막 시점의 일중 손익률(동기화). 직전 시점 대비 보정될 수 있습니다.",
    },
    "weekly_return_pct": {
        "label": "이번 주 손익률",
        "hint": "자산(equity) 곡선: 이번 주 월요일(UTC) 이후 첫 시점 대비.",
    },
    "monthly_return_pct": {
        "label": "이번 달 손익률",
        "hint": "자산(equity) 곡선: 이번 달 1일(UTC) 이후 첫 시점 대비.",
    },
    "cumulative_return_pct": {
        "label": "기간 누적 수익률(자산)",
        "hint": "필터 구간 첫·마지막 equity 비율. 브로커 동기화 자산 기준입니다.",
    },
    "net_cumulative_return_pct": {
        "label": "누적 수익률(동일: 자산 기준)",
        "hint": "cumulative_return_pct 와 동일 값입니다. 대시보드 flat 필드와 용어를 맞추기 위한 별칭입니다.",
    },
    "win_rate_pct": {
        "label": "승률(매도 건수 기준)",
        "hint": "매도 체결마다 FIFO 순손익(net)이 플러스인 비율.",
    },
    "payoff_ratio": {
        "label": "손익비",
        "hint": "순손익(net) 기준 평균 이익 ÷ 평균 손실.",
    },
    "max_drawdown_pct": {
        "label": "최대 낙폭(%)",
        "hint": "필터 구간 equity 곡선의 롤링 피크 대비 최대 하락.",
    },
    "gross_realized_pnl": {
        "label": "실현 매매차익(세전)",
        "hint": "매도가×수량 − 매수 원가(매수 수수료 제외) 합계. 매도 수수료·세 전 가격차입니다.",
    },
    "net_realized_pnl": {
        "label": "실현 순손익(추정)",
        "hint": "매도 순현금 − 매입총비용(FIFO). 행에 수수료·세가 없으면 KIS/KRX 비율로 추정합니다.",
    },
}


def build_performance_metrics(
    cfg: BackendSettings,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    strategy_id: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    snap = load_last_snapshot(cfg) or {}
    pnl_rows = filter_pnl_rows(load_pnl_rows(cfg), start_date, end_date)
    fill_rows = filter_fill_rows(load_fill_rows(cfg), start_date, end_date, strategy_id, symbol)
    trades, replay = replay_fills(cfg, fill_rows)

    eq_bundle = compute_equity_returns(pnl_rows, snap)

    wins = [t for t in trades if float(t.get("net_pnl") or t.get("pnl") or 0.0) > 0]
    losses = [t for t in trades if float(t.get("net_pnl") or t.get("pnl") or 0.0) < 0]
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    avg_win = sum(float(t["net_pnl"]) for t in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(float(t["net_pnl"]) for t in losses) / len(losses)) if losses else 0.0
    payoff = (avg_win / avg_loss) if avg_loss > 0 else (1.0 if avg_win > 0 else 0.0)

    explicit_sell_rows = sum(1 for t in replay.trades if t.fee_input_mode == "explicit_columns")
    sell_events = len(replay.trades)
    total_fees = replay.total_buy_fees + replay.total_sell_fees
    explicit_any = explicit_sell_rows > 0 or any(
        m == "explicit_columns" for m in replay.fee_mode_counts
    )
    all_sells_explicit = sell_events > 0 and explicit_sell_rows == sell_events

    assumptions = [
        {
            "id": "fifo_realized",
            "text": "실현손익은 매도 체결마다 FIFO로 매칭합니다. 필터로 일부 체결만 보면 이전 매수가 빠져 왜곡될 수 있습니다.",
        },
        {
            "id": "fees_taxes_korea",
            "text": (
                "체결 JSON에 수수료·세금이 없으면 환경변수 비율로 추정합니다: "
                f"KIS_BUY_FEE_RATE={cfg.kis_buy_fee_rate}, KIS_SELL_FEE_RATE={cfg.kis_sell_fee_rate}, "
                f"KRX_SELL_TAX_RATE={cfg.krx_sell_tax_rate} (소수, 예 0.0015=0.15%). "
                "실제 증권사·종목·거래대금에 따라 다를 수 있습니다."
            ),
        },
        {
            "id": "equity_vs_fills",
            "text": "누적·월간 등 수익률(%)은 pnl_history의 equity(브로커 동기화 자산) 기준이며, 체결 FIFO 순손익 합(net_realized_pnl)과 원단위가 다를 수 있습니다.",
        },
    ]

    calculation_basis = {
        "returns": {
            "definition": "equity_curve_from_pnl_history_jsonl",
            "timezone": "UTC for week/month anchors",
            "daily": "last_row_daily_pnl_pct_or_equity_delta",
            "weekly": "equity_end_over_first_point_on_or_after_week_monday_utc",
            "monthly": "equity_end_over_first_point_on_or_after_month_first_utc",
            "cumulative": "equity_end_over_first_point_in_filtered_window",
            "net_cumulative_return_pct": "same_as_cumulative_equity_based",
            "anchors": {
                "weekly_anchor_ts_utc": eq_bundle.weekly_anchor_ts,
                "monthly_anchor_ts_utc": eq_bundle.monthly_anchor_ts,
            },
        },
        "realized_pnl_fills": {
            "definition": "fifo_per_sell_fill",
            "gross_realized_pnl": "sum(sell_gross - matched_pure_buy_cost)",
            "net_realized_pnl": "sum(sell_net_proceeds - matched_cost_including_buy_fee)",
            "total_fees": "sum(all_buy_fees_in_replay + sell_fees_on_sells)",
            "total_taxes": "sum(sell_side_tax_estimates_or_columns)",
        },
        "snapshot_fields": {
            "realized_pnl": "portfolio_sync_state.json (브로커/리플레이 스냅샷)",
            "unrealized_pnl": "portfolio_sync_state.json",
        },
    }

    data_quality = {
        "pnl_history_points_used": len(pnl_rows),
        "fills_used": len(fill_rows),
        "sell_trades_count": sell_events,
        "fee_tax_source": "explicit_columns" if explicit_any else "estimated_rates_only",
        "explicit_fee_rows_estimate": explicit_sell_rows,
        "fees_and_taxes_in_trade_replay": True,
        "sell_side_fees_all_from_broker_columns": all_sells_explicit,
        "buy_side_may_still_use_kis_rates": True,
        "fifo_vs_avg_cost_discrepancy": round(replay.net_realized_pnl - replay.avg_cost_total_realized, 4)
        if sell_events
        else 0.0,
        "equity_return_notes": eq_bundle.notes,
        "replay_warnings": replay.replay_warnings[:20],
        "win_rate_basis": "fifo_net_pnl_per_sell_fill",
        "returns_are_equity_based": True,
        "filter_may_break_fifo": bool(start_date or end_date or strategy_id or symbol),
    }

    return {
        "daily_return_pct": eq_bundle.daily_return_pct,
        "weekly_return_pct": eq_bundle.weekly_return_pct,
        "monthly_return_pct": eq_bundle.monthly_return_pct,
        "cumulative_return_pct": eq_bundle.cumulative_return_pct,
        "net_cumulative_return_pct": eq_bundle.cumulative_return_pct,
        "realized_pnl": float(snap.get("realized_pnl") or 0.0),
        "unrealized_pnl": float(snap.get("unrealized_pnl") or 0.0),
        "gross_realized_pnl": replay.gross_realized_pnl,
        "total_fees": round(total_fees, 4),
        "total_taxes": replay.total_taxes,
        "net_realized_pnl": replay.net_realized_pnl,
        "max_drawdown_pct": eq_bundle.max_drawdown_pct,
        "win_rate_pct": round(win_rate, 4),
        "payoff_ratio": round(payoff, 4),
        "realized_pnl_fifo_total": replay.net_realized_pnl,
        "realized_pnl_avg_cost_total": replay.avg_cost_total_realized,
        "data_source": "pnl_history_jsonl_and_fills_jsonl_and_snapshot",
        "value_sources": {
            "daily_return_pct": "pnl_history_last_row_or_equity_delta",
            "weekly_return_pct": "pnl_history_equity_vs_week_anchor",
            "monthly_return_pct": "pnl_history_equity_vs_month_anchor",
            "cumulative_return_pct": "pnl_history_equity_window",
            "net_cumulative_return_pct": "same_as_cumulative_return_pct",
            "gross_realized_pnl": "fills_fifo_replay_gross",
            "total_fees": "fills_replay_buy_plus_sell_fees",
            "total_taxes": "fills_replay_sell_tax",
            "net_realized_pnl": "fills_fifo_replay_net",
            "realized_pnl": "portfolio_snapshot",
            "unrealized_pnl": "portfolio_snapshot",
            "max_drawdown_pct": "pnl_history_equity_curve",
            "win_rate_pct": "fills_fifo_net_per_sell",
            "payoff_ratio": "fills_fifo_net_per_sell",
        },
        "calculation_basis": calculation_basis,
        "assumptions": assumptions,
        "data_quality": data_quality,
        "display_labels_ko": _DISPLAY_LABELS_KO,
        "fee_rates_applied": {
            "kis_buy_fee_rate": cfg.kis_buy_fee_rate,
            "kis_sell_fee_rate": cfg.kis_sell_fee_rate,
            "krx_sell_tax_rate": cfg.krx_sell_tax_rate,
        },
    }


def build_dashboard_performance_block() -> dict[str, Any]:
    """필터 없음 — 대시보드 flat 필드와 동일 정의."""
    cfg = get_backend_settings()
    m = build_performance_metrics(cfg)
    return {
        "today_return_pct": m["daily_return_pct"],
        "monthly_return_pct": m["monthly_return_pct"],
        "cumulative_return_pct": m["cumulative_return_pct"],
        "net_cumulative_return_pct": m["net_cumulative_return_pct"],
        "gross_realized_pnl": m["gross_realized_pnl"],
        "total_fees": m["total_fees"],
        "total_taxes": m["total_taxes"],
        "net_realized_pnl": m["net_realized_pnl"],
        "max_drawdown_pct": m["max_drawdown_pct"],
        "win_rate_pct": m["win_rate_pct"],
        "payoff_ratio": m["payoff_ratio"],
        "data_quality": m["data_quality"],
        "fee_rates_applied": m["fee_rates_applied"],
        "assumptions_tail": (m.get("assumptions") or [])[:3],
    }
