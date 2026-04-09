"""FIFO·수익률·수수료/세금 집계 단위 테스트."""

from __future__ import annotations

from backend.app.portfolio.performance_math import (
    compute_equity_returns,
    fifo_and_avg_cost_replay,
    fifo_trade_rows_as_dicts,
    sort_pnl_rows_by_ts,
)


def test_fifo_differs_from_average_cost() -> None:
    fills = [
        {"exec_id": "1", "symbol": "AAA", "side": "buy", "quantity": 10, "price": 100.0, "ord_dt": "20250101", "ord_tmd": "090000"},
        {"exec_id": "2", "symbol": "AAA", "side": "buy", "quantity": 10, "price": 200.0, "ord_dt": "20250102", "ord_tmd": "090000"},
        {"exec_id": "3", "symbol": "AAA", "side": "sell", "quantity": 15, "price": 180.0, "ord_dt": "20250103", "ord_tmd": "090000"},
    ]
    r = fifo_and_avg_cost_replay(fills, buy_fee_rate=0.0, sell_fee_rate=0.0, sell_tax_rate=0.0)
    assert len(r.trades) == 1
    assert abs(r.trades[0].net_pnl - 700.0) < 1e-6
    assert abs(r.trades[0].gross_pnl - 700.0) < 1e-6
    assert abs(r.net_realized_pnl - 700.0) < 1e-6
    assert abs(r.gross_realized_pnl - 700.0) < 1e-6
    assert abs(r.trades[0].realized_pnl_avg_cost - 450.0) < 1e-6


def test_sell_fees_reduce_fifo_pnl() -> None:
    fills = [
        {"exec_id": "1", "symbol": "BBB", "side": "buy", "quantity": 10, "price": 100.0, "ord_dt": "20250101", "ord_tmd": "090000"},
        {"exec_id": "2", "symbol": "BBB", "side": "sell", "quantity": 10, "price": 110.0, "ord_dt": "20250102", "ord_tmd": "090000"},
    ]
    r0 = fifo_and_avg_cost_replay(fills, buy_fee_rate=0.0, sell_fee_rate=0.0, sell_tax_rate=0.0)
    r1 = fifo_and_avg_cost_replay(fills, buy_fee_rate=0.0, sell_fee_rate=0.01, sell_tax_rate=0.0)
    assert r0.net_realized_pnl > r1.net_realized_pnl
    assert r0.total_sell_fees < r1.total_sell_fees


def test_explicit_fee_column() -> None:
    fills = [
        {"exec_id": "1", "symbol": "CCC", "side": "buy", "quantity": 10, "price": 100.0, "fee": 50.0, "ord_dt": "20250101", "ord_tmd": "090000"},
        {"exec_id": "2", "symbol": "CCC", "side": "sell", "quantity": 10, "price": 110.0, "fee": 10.0, "tax": 5.0, "ord_dt": "20250102", "ord_tmd": "090000"},
    ]
    r = fifo_and_avg_cost_replay(fills, buy_fee_rate=0.5, sell_fee_rate=0.5, sell_tax_rate=0.5)
    assert abs(r.net_realized_pnl - 35.0) < 1e-6
    assert r.trades[0].fee_input_mode == "explicit_columns"
    assert abs(r.total_buy_fees - 50.0) < 1e-6
    assert abs(r.total_sell_fees - 10.0) < 1e-6
    assert abs(r.total_taxes - 5.0) < 1e-6


def test_equity_returns_cumulative_and_mdd() -> None:
    snap: dict = {"daily_pnl_pct": 0.0, "cumulative_pnl_pct": 0.0}
    rows = sort_pnl_rows_by_ts(
        [
            {"ts_utc": "2025-01-01T00:00:00+00:00", "equity": 100.0, "daily_pnl_pct": 0.0},
            {"ts_utc": "2025-01-02T00:00:00+00:00", "equity": 110.0, "daily_pnl_pct": 1.0},
            {"ts_utc": "2025-01-03T00:00:00+00:00", "equity": 88.0, "daily_pnl_pct": -2.0},
        ]
    )
    b = compute_equity_returns(rows, snap)
    assert abs(b.cumulative_return_pct - (-12.0)) < 1e-6
    assert b.max_drawdown_pct < 0
    assert b.monthly_anchor_ts is not None


def test_trade_dicts_reverse_chronological() -> None:
    fills = [
        {"exec_id": "a", "symbol": "D", "side": "buy", "quantity": 1, "price": 1.0, "ord_dt": "20250101", "ord_tmd": "090000"},
        {"exec_id": "b", "symbol": "D", "side": "sell", "quantity": 1, "price": 2.0, "ord_dt": "20250102", "ord_tmd": "090000"},
    ]
    r = fifo_and_avg_cost_replay(fills, buy_fee_rate=0.0, sell_fee_rate=0.0, sell_tax_rate=0.0)
    d = fifo_trade_rows_as_dicts(r)
    assert d[0]["trade_id"] == "b"
    assert "gross_pnl" in d[0] and "net_pnl" in d[0] and "tax" in d[0]
