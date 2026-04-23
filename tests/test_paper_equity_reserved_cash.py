from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from app.brokers.base_broker import AccountEquitySnapshot, BaseBroker, Fill, OpenOrder, PositionView
from app.scheduler.equity_tracker import EquityTracker
from app.scheduler.intraday_jobs import IntradaySchedulerJobs

_KST = ZoneInfo("Asia/Seoul")


class _NoopStrategy:
    intraday_state = None
    last_diagnostics = []
    last_intraday_filter_breakdown = []
    last_intraday_signal_breakdown = {}
    intraday_session_context = {
        "krx_session_state": "regular",
        "fetch_allowed": True,
        "order_allowed": True,
        "fetch_block_reason": "",
        "order_block_reason": "",
        "regular_session_kst": True,
    }
    timeframe_label = "1m"

    def generate_orders(self, context: object) -> list[object]:
        return []


class _EquityStubBroker(BaseBroker):
    def __init__(self, *, orderable_cash: float, cash_total: float, reserved: float = 0.0) -> None:
        self.initial_cash = 100.0
        self._snap = AccountEquitySnapshot(
            orderable_cash=float(orderable_cash),
            cash_total=float(cash_total),
            reserved_cash_open_buys=float(reserved),
            positions_market_value=None,
            source_of_truth="stub",
            open_buy_order_count=1 if reserved > 0 else 0,
            open_buy_order_missing_price_count=0,
            reserved_cash_estimation_method="stub",
            raw_balance_summary={},
        )

    def get_cash(self) -> float:
        return float(self._snap.orderable_cash)

    def get_account_equity_snapshot(self) -> AccountEquitySnapshot:
        return self._snap

    def get_positions(self) -> list[PositionView]:
        return []

    def place_order(self, order: object) -> object:
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> object:
        raise NotImplementedError

    def get_open_orders(self) -> list[OpenOrder]:
        return []

    def get_fills(self) -> list[Fill]:
        return []


def _write_equity_tracker_state(path: Path, *, day_open_equity: float) -> None:
    today = datetime.now(_KST).strftime("%Y-%m-%d")
    now_iso = datetime.now(_KST).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "baseline_equity": float(day_open_equity),
                "baseline_at_iso": now_iso,
                "day_key_kst": today,
                "day_open_equity": float(day_open_equity),
            }
        ),
        encoding="utf-8",
    )


def _mk_min_universe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["005930"] * 3,
            "date": pd.date_range("2026-04-14 09:00", periods=3, freq="1min", tz=_KST),
            "open": [50000.0] * 3,
            "high": [50100.0] * 3,
            "low": [49900.0] * 3,
            "close": [50050.0] * 3,
            "volume": [1000.0] * 3,
        }
    )


def _mk_index() -> pd.DataFrame:
    return pd.DataFrame({"date": pd.date_range("2026-01-01", periods=5, freq="D", tz=_KST), "close": range(2400, 2405)})


def test_reserved_cash_does_not_trigger_fake_daily_loss_halt(tmp_path: Path) -> None:
    state_path = tmp_path / "eq.json"
    _write_equity_tracker_state(state_path, day_open_equity=100.0)
    eq = EquityTracker(state_path)

    broker = _EquityStubBroker(orderable_cash=70.0, cash_total=100.0, reserved=30.0)
    jobs = IntradaySchedulerJobs(
        strategy=_NoopStrategy(),
        broker=broker,
        equity_tracker=eq,
        state_store=None,
    )
    uni = _mk_min_universe()
    kospi = _mk_index()
    rep = jobs.run_intraday_cycle(
        universe_tf=uni,
        kospi_index=kospi,
        sp500_index=kospi,
        timeframe="1m",
        quote_by_symbol={},
        forced_flatten=False,
        regular_session_kst=True,
    )
    assert rep.get("risk_halt_new_entries") is False
    assert float(rep.get("daily_pnl_pct_snapshot") or 0.0) == 0.0
    assert float(rep.get("equity") or 0.0) == 100.0
    assert float(rep.get("cash") or 0.0) == 70.0
    assert float(rep.get("cash_total") or 0.0) == 100.0
    assert float(rep.get("reserved_cash_open_buys") or 0.0) == 30.0


def test_real_daily_loss_still_triggers_halt(tmp_path: Path) -> None:
    state_path = tmp_path / "eq.json"
    _write_equity_tracker_state(state_path, day_open_equity=100.0)
    eq = EquityTracker(state_path)

    broker = _EquityStubBroker(orderable_cash=70.0, cash_total=70.0)
    jobs = IntradaySchedulerJobs(
        strategy=_NoopStrategy(),
        broker=broker,
        equity_tracker=eq,
        state_store=None,
    )
    uni = _mk_min_universe()
    kospi = _mk_index()
    rep = jobs.run_intraday_cycle(
        universe_tf=uni,
        kospi_index=kospi,
        sp500_index=kospi,
        timeframe="1m",
        quote_by_symbol={},
        forced_flatten=False,
        regular_session_kst=True,
    )
    assert rep.get("risk_halt_new_entries") is True
    assert float(rep.get("daily_pnl_pct_snapshot") or 0.0) <= -20.0


def test_kis_paper_equity_prefers_nass_amt_when_present() -> None:
    from app.brokers.kis_paper_broker import KisPaperBroker

    class _Client:
        base_url = "https://openapivts.koreainvestment.com:29443"

        def get_balance(self, account_no: str, account_product_code: str) -> dict:
            _ = (account_no, account_product_code)
            return {
                "output2": [
                    {
                        "ord_psbl_cash": "900",
                        "dnca_tot_amt": "1000",
                        "nass_amt": "1200",
                        "evlu_amt_smtl": "0",
                    }
                ],
                "output1": [],
            }

        def inquire_nccs(self, *args: object, **kwargs: object) -> dict:
            _ = (args, kwargs)
            return {"output1": []}

    b = KisPaperBroker(kis_client=_Client(), account_no="123", account_product_code="01")
    s = b.get_account_equity_snapshot()
    assert s.source_of_truth == "KIS:nass_amt"
    assert s.cash_total == 1000.0
    assert s.orderable_cash == 900.0


def test_kis_paper_equity_reconstructs_reserved_cash_when_total_missing() -> None:
    from app.brokers.kis_paper_broker import KisPaperBroker

    class _Client:
        base_url = "https://openapivts.koreainvestment.com:29443"

        def get_balance(self, account_no: str, account_product_code: str) -> dict:
            _ = (account_no, account_product_code)
            return {
                "output2": [{"ord_psbl_cash": "70"}],
                "output1": [],
            }

        def inquire_nccs(self, *args: object, **kwargs: object) -> dict:
            _ = (args, kwargs)
            return {
                "output1": [
                    {
                        "pdno": "005930",
                        "odno": "A1",
                        "sll_buy_dvsn_cd": "02",
                        "ord_qty": "30",
                        "tot_ccld_qty": "0",
                        "rmn_qty": "30",
                        "ord_unpr": "1",
                        "ord_tmd": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
                    }
                ]
            }

    b = KisPaperBroker(kis_client=_Client(), account_no="123", account_product_code="01")
    s = b.get_account_equity_snapshot()
    assert s.cash_total is None
    assert s.orderable_cash == 70.0
    assert s.reserved_cash_open_buys == 30.0
    assert s.source_of_truth == "orderable+reserved+positions"
