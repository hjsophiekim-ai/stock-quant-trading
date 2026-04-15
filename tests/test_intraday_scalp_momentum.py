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
from app.config import get_settings
from app.strategy.base_strategy import StrategyContext
from app.strategy.intraday_paper_state import IntradayPaperState, IntradayPaperStateStore
from app.strategy.market_regime import MarketRegimeConfig
from app.strategy.scalp_momentum_v1_strategy import ScalpMomentumV1Strategy
from app.strategy.scalp_momentum_v2_strategy import ScalpMomentumV2Strategy
from app.strategy.scalp_momentum_v3_strategy import ScalpMomentumV3Strategy


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
        "app.strategy.scalp_momentum_v1_strategy.get_krx_session_state_kst",
        lambda *a, **k: "regular",
    )
    monkeypatch.setattr(
        "app.strategy.scalp_momentum_v1_strategy.should_force_flatten_before_close_kst",
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


def _build_intraday_prices(
    symbol: str,
    bars: int,
    *,
    trend_step: float = 0.25,
    anchor_kst: datetime | None = None,
) -> pd.DataFrame:
    now = (anchor_kst or datetime.now(_KST)).replace(second=0, microsecond=0)
    start = now - timedelta(minutes=bars - 1)
    rows = []
    for i in range(bars):
        px = 100.0 + (i * trend_step)
        rows.append(
            {
                "symbol": symbol,
                "date": start + timedelta(minutes=i),
                "open": px - 0.03,
                "high": px + 0.09,
                "low": px - 0.08,
                "close": px,
                "volume": 10_000.0 + (i * 150.0),
            }
        )
    return pd.DataFrame(rows)


def _build_context_from_prices(price_df: pd.DataFrame) -> StrategyContext:
    kospi = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=40, freq="D", tz=_KST),
            "close": [2500.0 + (i * 0.5) for i in range(40)],
        }
    )
    sp500 = kospi.copy()
    vol = pd.DataFrame({"date": kospi["date"], "value": [1.0] * len(kospi)})
    return StrategyContext(
        prices=price_df,
        kospi_index=kospi,
        sp500_index=sp500,
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]),
        volatility_index=vol,
    )


def test_scalp_momentum_v2_score_based_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.strategy.scalp_momentum_v2_strategy.get_krx_session_state_kst", lambda *a, **k: "regular")
    monkeypatch.setattr("app.strategy.scalp_momentum_v2_strategy.should_force_flatten_before_close_kst", lambda **_: False)
    # 세션/앵커 시각에 따라 마지막 봉 body%가 달라져 chase_candle 에 걸릴 수 있어 고정
    monkeypatch.setattr("app.strategy.scalp_momentum_v2_strategy.last_bar_body_pct", lambda _df: 0.8)
    strat = ScalpMomentumV2Strategy()
    strat.intraday_state = IntradayPaperState()
    strat.quote_by_symbol = {
        "005930": {
            "output": {
                "acml_vol": "250000000",
                "acml_tr_pbmn": "5000000000000",
                "bidp": "105.0",
                "askp": "105.2",
            }
        }
    }
    prices = _build_intraday_prices(
        "005930",
        26,
        trend_step=0.18,
        anchor_kst=datetime(2026, 4, 14, 10, 0, tzinfo=_KST),
    )
    sigs = strat.generate_signals(_build_context_from_prices(prices))
    assert any(s.side == "buy" for s in sigs)
    assert len(strat.last_diagnostics) >= 1
    assert "total_score" in strat.last_diagnostics[0]
    assert "ema_align" in strat.last_diagnostics[0]


def test_scalp_momentum_v3_entry_and_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.strategy.scalp_momentum_v3_strategy.get_krx_session_state_kst", lambda *a, **k: "regular")
    monkeypatch.setattr("app.strategy.scalp_momentum_v3_strategy.should_force_flatten_before_close_kst", lambda **_: False)
    monkeypatch.setattr("app.strategy.scalp_momentum_v3_strategy.last_bar_body_pct", lambda _df: 0.8)
    # 진입 가능 케이스
    strat_ok = ScalpMomentumV3Strategy()
    strat_ok.intraday_state = IntradayPaperState()
    strat_ok.quote_by_symbol = {
        "000660": {
            "output": {
                "acml_vol": "200000000",
                "acml_tr_pbmn": "4500000000000",
                "bidp": "110.0",
                "askp": "110.3",
            }
        }
    }
    prices_ok = _build_intraday_prices(
        "000660",
        22,
        trend_step=0.15,
        anchor_kst=datetime(2026, 4, 14, 10, 0, tzinfo=_KST),
    )
    sigs_ok = strat_ok.generate_signals(_build_context_from_prices(prices_ok))
    assert any(s.side == "buy" for s in sigs_ok)

    # 고변동 리스크 차단 케이스
    strat_block = ScalpMomentumV3Strategy(regime_config=MarketRegimeConfig(high_volatility_threshold=0.1))
    strat_block.intraday_state = IntradayPaperState()
    strat_block.quote_by_symbol = strat_ok.quote_by_symbol
    # 큰 변동으로 high_volatility_risk를 유도
    kospi_dates = pd.date_range("2026-01-01", periods=40, freq="D", tz=_KST)
    kospi_high_vol = pd.DataFrame({"date": kospi_dates, "close": [2500 + ((-1) ** i) * 120 for i in range(40)]})
    ctx_block = StrategyContext(
        prices=prices_ok,
        kospi_index=kospi_high_vol,
        sp500_index=kospi_high_vol.copy(),
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]),
        volatility_index=pd.DataFrame({"date": kospi_dates, "value": [10.0] * len(kospi_dates)}),
    )
    sigs_block = strat_block.generate_signals(ctx_block)
    assert not any(s.side == "buy" for s in sigs_block)
    assert strat_block.last_intraday_signal_breakdown.get("blocked") == "high_volatility_risk_no_entry"


def test_intraday_symbol_fallback_when_env_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAPER_INTRADAY_SYMBOLS", raising=False)
    monkeypatch.delenv("PAPER_TRADING_SYMBOLS", raising=False)
    get_settings.cache_clear()
    cfg = get_settings()
    symbols = cfg.resolved_intraday_symbol_list()
    assert 20 <= len(symbols) <= 30
    assert "005930" in symbols
    assert "000660" in symbols
