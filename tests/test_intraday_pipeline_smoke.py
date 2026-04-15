"""인트라데이: 합성 유니버스로 전략→주문 경로 스모크(분봉 API 없이)."""

from __future__ import annotations

import pandas as pd
import pytest
from zoneinfo import ZoneInfo

from app.brokers.paper_broker import PaperBroker
from app.orders.models import OrderRequest
from app.risk.rules import RiskLimits, RiskRules

_SMOKE_LIMITS = RiskLimits(
    min_position_weight=0.001,
    max_position_weight=0.99,
    max_positions=20,
    daily_loss_limit_pct=99.0,
    total_loss_limit_pct=99.0,
    default_stop_loss_pct=99.0,
)
from app.scheduler.intraday_jobs import IntradaySchedulerJobs
from app.strategy.intraday_common import IntradaySessionSnapshot
from app.strategy.market_regime import MarketRegimeConfig

_KST = ZoneInfo("Asia/Seoul")


class _AlwaysBuyStrategy:
    """분봉·시세와 무관하게 매수 1건 생성 (주문 파이프라인 검증용)."""

    regime_config = MarketRegimeConfig()
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

    def generate_orders(self, context: object) -> list[OrderRequest]:
        return [
            OrderRequest(
                symbol="005930",
                side="buy",
                quantity=1,
                price=50_000.0,
                stop_loss_pct=1.0,
                strategy_id="smoke_intraday",
            )
        ]


def test_intraday_cycle_smoke_generates_and_accepts_order() -> None:
    uni = pd.DataFrame(
        {
            "symbol": ["005930"] * 30,
            "date": pd.date_range("2026-04-14 09:00", periods=30, freq="1min", tz=_KST),
            "open": [50000.0] * 30,
            "high": [50100.0] * 30,
            "low": [49900.0] * 30,
            "close": [50050.0] * 30,
            "volume": [1000.0] * 30,
        }
    )
    kospi = pd.DataFrame(
        {"date": pd.date_range("2026-01-01", periods=20, freq="D", tz=_KST), "close": range(2400, 2420)}
    )
    sp500 = kospi.copy()
    snap = IntradaySessionSnapshot(
        state="regular",
        fetch_allowed=True,
        order_allowed=True,
        fetch_block_reason="",
        order_block_reason="",
        regular_session_kst=True,
    )
    jobs = IntradaySchedulerJobs(
        strategy=_AlwaysBuyStrategy(),
        broker=PaperBroker(initial_cash=10_000_000.0),
        risk_rules=RiskRules(_SMOKE_LIMITS),
        kill_switch=None,
        equity_tracker=None,
        state_store=None,
    )
    rep = jobs.run_intraday_cycle(
        universe_tf=uni,
        kospi_index=kospi,
        sp500_index=sp500,
        timeframe="1m",
        quote_by_symbol={"005930": {"output": {"acml_vol": "1e9", "acml_tr_pbmn": "5e12", "bidp": "50000", "askp": "50010"}}},
        forced_flatten=False,
        paper_trading_symbols_resolved=["005930"],
        intraday_bar_fetch_summary=[{"symbol": "005930", "fetch_error": "", "bars_1m": 30}],
        intraday_universe_row_count=30,
        regular_session_kst=True,
        intraday_session_snapshot=snap,
    )
    assert int(rep.get("generated_order_count") or 0) >= 1
    assert int(rep.get("accepted_orders") or 0) >= 1


def test_summarize_fetch_errors_top3() -> None:
    from app.scheduler.kis_intraday import summarize_intraday_fetch_errors

    rows = [
        {"fetch_error": "api_error"},
        {"fetch_error": "api_error"},
        {"fetch_error": "skipped_closed_session"},
        {"fetch_error": ""},
    ]
    s = summarize_intraday_fetch_errors(rows, top_n=3)
    assert s[0]["fetch_error"] == "api_error"
    assert s[0]["count"] == 2


def test_kis_client_error_fields_helper() -> None:
    from app.clients.kis_client import KISClientError
    from app.scheduler.kis_intraday import kis_client_error_to_fetch_row_fields

    exc = KISClientError(
        "KIS HTTP 403",
        kis_context={
            "path": "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            "tr_id": "FHKST03010200",
            "http_status": 403,
            "params": {"FID_COND_MRKT_DIV_CODE": "J"},
            "rate_limit": False,
        },
    )
    d = kis_client_error_to_fetch_row_fields(exc)
    assert d["kis_http_status"] == 403
    assert "inquire-time-itemchartprice" in str(d["kis_path"])
    assert d["fetch_error_detail_full"] == "KIS HTTP 403"
