"""포트폴리오 체결 리플레이·KIS 잔고 파서."""

from app.clients.kis_parsers import balance_snapshot_from_payload, normalized_fills_from_ccld_payload
from backend.app.portfolio.sync_engine import replay_fills_for_pnl


def test_replay_split_buys_weighted_average_and_partial_sell() -> None:
    fills = [
        {
            "exec_id": "1",
            "symbol": "005930",
            "side": "buy",
            "quantity": 10,
            "price": 100.0,
            "ord_dt": "20240101",
            "ord_tmd": "090000",
            "strategy_id": "s1",
        },
        {
            "exec_id": "2",
            "symbol": "005930",
            "side": "buy",
            "quantity": 10,
            "price": 120.0,
            "ord_dt": "20240101",
            "ord_tmd": "090100",
            "strategy_id": "s1",
        },
        {
            "exec_id": "3",
            "symbol": "005930",
            "side": "sell",
            "quantity": 10,
            "price": 150.0,
            "ord_dt": "20240101",
            "ord_tmd": "090200",
            "strategy_id": "s1",
        },
    ]
    r = replay_fills_for_pnl(fills)
    pos = r.positions.get("005930")
    assert pos is not None
    assert pos.quantity == 10
    assert abs(pos.average_price - 110.0) < 1e-6
    assert abs(r.total_realized - 400.0) < 1e-6
    assert abs(r.realized_by_symbol["005930"] - 400.0) < 1e-6
    assert abs(r.realized_by_strategy["s1"] - 400.0) < 1e-6


def test_balance_snapshot_from_payload_minimal() -> None:
    payload = {
        "output2": [{"ord_psbl_cash": "1000000", "tot_evlu_amt": "5000000"}],
        "output1": [
            {
                "pdno": "005930",
                "hldg_qty": "5",
                "pchs_avg_pric": "70000",
                "prpr": "71000",
                "evlu_pfls_amt": "5000",
                "evlu_amt": "355000",
            }
        ],
    }
    snap = balance_snapshot_from_payload(payload)
    assert snap["cash"] == 1_000_000.0
    assert len(snap["positions"]) == 1
    p0 = snap["positions"][0]
    assert p0["symbol"] == "005930"
    assert p0["quantity"] == 5
    assert p0["average_price"] == 70000.0
    assert p0["unrealized_pnl_kis"] == 5000.0


def test_normalized_fills_from_ccld() -> None:
    payload = {
        "output1": [
            {
                "pdno": "005930",
                "sll_buy_dvsn_cd": "02",
                "ccld_qty": "3",
                "ccld_untp": "70000",
                "odno": "0001",
                "ord_dt": "20240102",
                "ord_tmd": "100000",
            }
        ]
    }
    rows = normalized_fills_from_ccld_payload(payload)
    assert len(rows) == 1
    assert rows[0]["side"] == "buy"
    assert rows[0]["quantity"] == 3
    assert rows[0]["price"] == 70000.0
