"""KRX 세션 상태·분봉 게이트·주문 차단 단위 테스트."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time
import pandas as pd
import pytest
from zoneinfo import ZoneInfo

from app.brokers.paper_broker import PaperBroker
from app.orders.models import OrderRequest
from app.scheduler.intraday_jobs import IntradaySchedulerJobs
from app.scheduler.kis_intraday import FETCH_SKIPPED_PREOPEN_DISABLED, build_intraday_universe_1m
from app.strategy.intraday_common import (
    IntradaySessionSnapshot,
    KrxSessionConfig,
    evaluate_intraday_fetch_gate,
    evaluate_intraday_order_gate,
    get_krx_session_state_kst,
    krx_session_config_from_settings,
)
from app.strategy.market_regime import MarketRegimeConfig

_KST = ZoneInfo("Asia/Seoul")

_BASE_CFG = KrxSessionConfig(
    preopen_start=time(8, 0),
    regular_open=time(9, 0),
    regular_close=time(15, 30),
    afterhours_close=time(18, 0),
    preopen_enabled=True,
    afterhours_enabled=True,
    extended_fetch_enabled=True,
    extended_order_enabled=False,
)


def _cfg(**kwargs: object) -> KrxSessionConfig:
    return replace(_BASE_CFG, **kwargs)


def test_get_krx_session_state_weekday_regular() -> None:
    dt = datetime(2026, 4, 14, 10, 0, tzinfo=_KST)
    assert get_krx_session_state_kst(dt, session_config=_cfg()) == "regular"


def test_get_krx_session_state_pre_open() -> None:
    dt = datetime(2026, 4, 14, 8, 30, tzinfo=_KST)
    assert get_krx_session_state_kst(dt, session_config=_cfg()) == "pre_open"


def test_get_krx_session_state_after_hours() -> None:
    dt = datetime(2026, 4, 14, 16, 0, tzinfo=_KST)
    assert get_krx_session_state_kst(dt, session_config=_cfg()) == "after_hours"


def test_get_krx_session_state_closed_weekend() -> None:
    dt = datetime(2026, 4, 12, 10, 0, tzinfo=_KST)
    assert get_krx_session_state_kst(dt, session_config=_cfg()) == "closed"


def test_fetch_gate_preopen_disabled() -> None:
    dt = datetime(2026, 4, 14, 8, 30, tzinfo=_KST)
    cfg = _cfg(preopen_enabled=False, extended_fetch_enabled=True)
    ok, reason = evaluate_intraday_fetch_gate(dt, session_config=cfg)
    assert ok is False
    assert reason == "skipped_preopen_disabled"


def test_fetch_gate_afterhours_disabled() -> None:
    dt = datetime(2026, 4, 14, 16, 0, tzinfo=_KST)
    cfg = _cfg(afterhours_enabled=False, extended_fetch_enabled=True)
    ok, reason = evaluate_intraday_fetch_gate(dt, session_config=cfg)
    assert ok is False
    assert reason == "skipped_afterhours_disabled"


def test_order_gate_after_hours_kis_regular_only() -> None:
    dt = datetime(2026, 4, 14, 16, 0, tzinfo=_KST)
    cfg = _cfg(extended_order_enabled=True)
    ok, reason = evaluate_intraday_order_gate(dt, session_config=cfg)
    assert ok is False
    assert reason == "kis_domestic_order_regular_hours_only"


def test_build_intraday_universe_skips_fetch_when_blocked() -> None:
    from unittest.mock import MagicMock

    called = {"n": 0}
    client = MagicMock()

    def _boom(*_a: object, **_k: object) -> None:
        called["n"] += 1
        raise AssertionError("API should not be called when fetch disallowed")

    client.get_time_itemchartprice.side_effect = _boom
    df, summary = build_intraday_universe_1m(
        client,
        ["005930"],
        intraday_fetch_allowed=False,
        intraday_fetch_block_reason=FETCH_SKIPPED_PREOPEN_DISABLED,
        session_state="pre_open",
        order_allowed=False,
    )
    assert df.empty
    assert called["n"] == 0
    assert len(summary) == 1
    assert summary[0]["fetch_error"] == FETCH_SKIPPED_PREOPEN_DISABLED
    assert summary[0]["fetch_allowed"] is False


def test_intraday_jobs_suppresses_orders_when_not_orderable() -> None:
    """order_allowed=False 이면 전략이 주문을 내도 브로커까지 가지 않는다."""

    class _S:
        regime_config = MarketRegimeConfig()
        intraday_state = None
        last_diagnostics = []
        last_intraday_filter_breakdown = []
        last_intraday_signal_breakdown = {}

        def generate_orders(self, _ctx: object) -> list[OrderRequest]:
            return [
                OrderRequest(
                    symbol="005930",
                    side="buy",
                    quantity=1,
                    price=70000.0,
                    stop_loss_pct=1.0,
                    strategy_id="t",
                )
            ]

    uni = pd.DataFrame(
        {
            "symbol": ["005930"] * 5,
            "date": pd.date_range("2026-04-14 09:00", periods=5, freq="1min", tz=_KST),
            "open": [1.0] * 5,
            "high": [1.0] * 5,
            "low": [1.0] * 5,
            "close": [1.0] * 5,
            "volume": [1.0] * 5,
        }
    )
    kospi = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=10, freq="D", tz=_KST), "close": range(2400, 2410)})
    sp500 = kospi.copy()
    snap = IntradaySessionSnapshot(
        state="after_hours",
        fetch_allowed=True,
        order_allowed=False,
        fetch_block_reason="",
        order_block_reason="kis_domestic_order_regular_hours_only",
        regular_session_kst=False,
    )
    jobs = IntradaySchedulerJobs(strategy=_S(), broker=PaperBroker(), kill_switch=None, equity_tracker=None, state_store=None)
    rep = jobs.run_intraday_cycle(
        universe_tf=uni,
        kospi_index=kospi,
        sp500_index=sp500,
        timeframe="1m",
        quote_by_symbol={},
        forced_flatten=False,
        paper_trading_symbols_resolved=["005930"],
        intraday_bar_fetch_summary=[],
        intraday_universe_row_count=5,
        regular_session_kst=False,
        intraday_session_snapshot=snap,
    )
    assert int(rep.get("generated_order_count") or 0) >= 1
    assert int(rep.get("accepted_orders") or 0) == 0
    assert int(rep.get("orders_blocked_session") or 0) >= 1


def test_krx_session_config_from_settings_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_KRX_REGULAR_OPEN_HHMM", "090000")
    from app.config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()
    sc = krx_session_config_from_settings(cfg)
    assert sc.regular_open == time(9, 0)
