"""인트라데이 분봉 변환·단타 전략 진단·상태 게이트."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from zoneinfo import ZoneInfo

from app.scheduler.kis_intraday import kis_time_chart_rows_to_ohlc_df, resample_minute_ohlc
from app.scheduler.intraday_jobs import IntradaySchedulerJobs
from app.strategy.base_strategy import StrategyContext
from app.strategy.intraday_paper_state import IntradayPaperState, IntradayPaperStateStore
from app.strategy.scalp_momentum_v1_strategy import ScalpMomentumV1Strategy


_KST = ZoneInfo("Asia/Seoul")


def test_minute_rows_to_ohlc_and_resample_3m() -> None:
    today = datetime.now(_KST).strftime("%Y%m%d")
    rows = []
    base = datetime.strptime(today + "090000", "%Y%m%d%H%M%S").replace(tzinfo=_KST)
    for i in range(9):
        t = base + timedelta(minutes=i)
        rows.append(
            {
                "stck_bsop_date": today,
                "stck_cntg_hour": t.strftime("%H%M%S"),
                "stck_oprc": 1000.0 + i,
                "stck_hgpr": 1005.0 + i,
                "stck_lwpr": 995.0 + i,
                "stck_clpr": 1002.0 + i,
                "cntg_vol": 1000.0 * (i + 1),
            }
        )
    df1 = kis_time_chart_rows_to_ohlc_df(rows, symbol="005930", default_date_yyyymmdd=today)
    assert len(df1) == 9
    df3 = resample_minute_ohlc(df1, 3)
    assert len(df3) == 3
    assert float(df3["volume"].sum()) == pytest.approx(float(df1["volume"].sum()))


def test_intraday_state_roll_day(tmp_path: Path) -> None:
    p = tmp_path / "st.json"
    store = IntradayPaperStateStore(p)
    st = IntradayPaperState(day_kst="20000101", trade_count_today=5)
    store.save(st)
    loaded = store.load()
    assert loaded.day_kst != "20000101"
    assert loaded.trade_count_today == 0


def test_forced_flatten_flag_in_report_fields(tmp_path: Path) -> None:
    """IntradaySchedulerJobs 리포트에 forced_flatten 등 메타가 포함되는지(목)."""
    from app.brokers.paper_broker import PaperBroker
    from app.risk.kill_switch import KillSwitch
    from app.risk.rules import RiskLimits, RiskRules
    from app.scheduler.equity_tracker import EquityTracker

    strat = ScalpMomentumV1Strategy()
    broker = PaperBroker(initial_cash=10_000_000.0)
    rules = RiskRules(RiskLimits(5.0, 15.0, 3.0))
    kill = KillSwitch(rules=rules)
    jobs = IntradaySchedulerJobs(
        strategy=strat,
        broker=broker,
        risk_rules=rules,
        kill_switch=kill,
        equity_tracker=EquityTracker(tmp_path / "eq.json"),
        state_store=None,
    )
    uni = pd.DataFrame(
        {
            "symbol": ["005930"] * 40,
            "date": pd.date_range("2026-04-14 09:00", periods=40, freq="1min", tz=_KST),
            "open": [50000.0] * 40,
            "high": [50100.0] * 40,
            "low": [49900.0] * 40,
            "close": [50050.0] * 40,
            "volume": [1000.0] * 40,
        }
    )
    kospi = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=30, freq="D", tz=_KST),
            "close": [2500.0 + i for i in range(30)],
        }
    )
    sp500 = kospi.copy()
    rep = jobs.run_intraday_cycle(
        universe_tf=uni,
        kospi_index=kospi,
        sp500_index=sp500,
        timeframe="3m",
        quote_by_symbol={"005930": {"output": {"acml_vol": "1e9", "acml_tr_pbmn": "5e12", "bidp": "50000", "askp": "50010"}}},
        forced_flatten=False,
    )
    assert "forced_flatten" in rep
    assert "trade_count_today" in rep
    assert "timeframe" in rep


def test_scalp_diagnostics_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    """진입은 막혀도 last_diagnostics·filter_breakdown 경로가 동작하는지."""
    monkeypatch.setattr(
        "app.strategy.intraday_common.is_regular_krx_session",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.strategy.intraday_common.should_force_flatten_before_close_kst",
        lambda **_: False,
    )
    strat = ScalpMomentumV1Strategy()
    strat.quote_by_symbol = {
        "005930": {"output": {"acml_vol": "2e8", "acml_tr_pbmn": "1e13", "bidp": "100", "askp": "100.2"}},
    }
    st = IntradayPaperState()
    strat.intraday_state = st
    rows = []
    today = datetime.now(_KST).strftime("%Y%m%d")
    base = datetime.strptime(today + "090000", "%Y%m%d%H%M%S").replace(tzinfo=_KST)
    for i in range(30):
        t = base + timedelta(minutes=i)
        rows.append(
            {
                "stck_bsop_date": today,
                "stck_cntg_hour": t.strftime("%H%M%S"),
                "stck_oprc": 1000.0,
                "stck_hgpr": 1001.0,
                "stck_lwpr": 999.0,
                "stck_clpr": 1000.0,
                "cntg_vol": 5000.0,
            }
        )
    df = kis_time_chart_rows_to_ohlc_df(rows, symbol="005930", default_date_yyyymmdd=today)
    df3 = resample_minute_ohlc(df, 3)
    kospi = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=40, freq="D", tz=_KST), "close": range(2400, 2440)})
    sp500 = kospi.copy()
    vol = pd.DataFrame({"date": kospi["date"], "value": [1.0] * len(kospi)})
    ctx = StrategyContext(
        prices=df3,
        kospi_index=kospi,
        sp500_index=sp500,
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]),
        volatility_index=vol,
    )
    sigs = strat.generate_signals(ctx)
    assert isinstance(strat.last_diagnostics, list)


def test_buy_gate_cooldown_and_duplicate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.brokers.paper_broker import PaperBroker
    from app.risk.rules import RiskLimits, RiskRules

    monkeypatch.setenv("PAPER_INTRADAY_DUPLICATE_ORDER_GUARD_SEC", "3600")
    from app.config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()

    jobs = IntradaySchedulerJobs(
        strategy=ScalpMomentumV1Strategy(),
        broker=PaperBroker(),
        risk_rules=RiskRules(RiskLimits(5, 15, 3)),
        kill_switch=None,
        equity_tracker=None,
        state_store=None,
    )
    st = IntradayPaperState()
    st.last_buy_mono["005930"] = __import__("time").monotonic()
    g = jobs._intraday_buy_gate("005930", st, cfg)
    assert g["ok"] is False

    st2 = IntradayPaperState()
    st2.cooldown_until_iso["005930"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    g2 = jobs._intraday_buy_gate("005930", st2, cfg)
    assert g2["ok"] is False
