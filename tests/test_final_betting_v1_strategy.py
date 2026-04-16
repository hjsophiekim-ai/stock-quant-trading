from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.config import get_settings
from app.strategy.base_strategy import StrategyContext
from app.strategy.final_betting_v1_strategy import (
    FinalBettingV1Strategy,
    _calendar_days_between,
    set_final_betting_debug_now,
)
from app.strategy.intraday_paper_state import IntradayPaperState, IntradayPaperStateStore

_KST = ZoneInfo("Asia/Seoul")


def _index_frame(n: int = 130) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=n, freq="D", tz=_KST),
            "close": [100.0 + 0.02 * i for i in range(n)],
            "value": [15.0 + 0.01 * i for i in range(n)],
        }
    )


def test_calendar_days_between() -> None:
    assert _calendar_days_between("20260101", "20260103") == 2
    assert _calendar_days_between("20260103", "20260101") == 2


def _minute_series(symbol: str, ymd: str) -> pd.DataFrame:
    """ymd KST 당일 09:00~15:20 근처 1분봉 (단조 상승 + 충분한 거래량)."""
    day = datetime.strptime(ymd, "%Y%m%d").replace(tzinfo=_KST)
    rows = []
    px = 100.0
    for i in range(380):
        ts = day.replace(hour=9, minute=0) + pd.Timedelta(minutes=i)
        if ts.hour == 15 and ts.minute > 20:
            break
        o, h, low, c = px, px + 0.15, px - 0.05, px + 0.08
        rows.append(
            {
                "symbol": symbol,
                "date": ts,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 12_000.0,
            }
        )
        px = c
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def _clear_fb_debug():
    yield
    set_final_betting_debug_now(None)
    get_settings.cache_clear()


def test_entry_blocked_outside_entry_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    strat = FinalBettingV1Strategy()
    set_final_betting_debug_now(datetime(2026, 4, 16, 10, 15, tzinfo=_KST))
    strat.intraday_state = IntradayPaperState(day_kst="20260416")
    strat.intraday_session_context = {"krx_session_state": "regular"}
    df = _minute_series("005930", "20260416")
    idx = _index_frame()
    ctx = StrategyContext(
        prices=df,
        kospi_index=idx[["date", "close"]].copy(),
        sp500_index=idx[["date", "close"]].copy(),
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
        volatility_index=idx[["date", "value"]].copy(),
    )
    sigs = strat.generate_signals(ctx)
    assert strat.last_intraday_signal_breakdown.get("entry_window") == "closed"
    assert all(s.side != "buy" for s in sigs)


def test_diag_blocked_insufficient_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    strat = FinalBettingV1Strategy()
    set_final_betting_debug_now(datetime(2026, 4, 16, 15, 12, tzinfo=_KST))
    strat.intraday_state = IntradayPaperState(day_kst="20260416")
    strat.intraday_session_context = {"krx_session_state": "regular"}
    tiny = pd.DataFrame(
        [
            {
                "symbol": "005930",
                "date": datetime(2026, 4, 16, 9, 0, tzinfo=_KST),
                "open": 1,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "volume": 1.0,
            }
        ]
    )
    idx = _index_frame()
    ctx = StrategyContext(
        prices=tiny,
        kospi_index=idx[["date", "close"]].copy(),
        sp500_index=idx[["date", "close"]].copy(),
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
        volatility_index=idx[["date", "value"]].copy(),
    )
    strat.generate_signals(ctx)
    assert strat.last_diagnostics
    assert strat.last_diagnostics[0].get("blocked_reason") == "insufficient_bars"


def test_overnight_exit_time_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    strat = FinalBettingV1Strategy()
    set_final_betting_debug_now(datetime(2026, 4, 17, 10, 35, tzinfo=_KST))
    st = IntradayPaperState(day_kst="20260417")
    st.final_betting_carry = {
        "positions": {
            "005930": {
                "entry_kst_date": "20260416",
                "ref_close": 100.0,
                "shares": 10,
                "partial_scaleout_done": False,
            }
        }
    }
    strat.intraday_state = st
    strat.intraday_session_context = {"krx_session_state": "regular"}
    df = _minute_series("005930", "20260417")
    idx = _index_frame()
    ctx = StrategyContext(
        prices=df,
        kospi_index=idx[["date", "close"]].copy(),
        sp500_index=idx[["date", "close"]].copy(),
        portfolio=pd.DataFrame([{"symbol": "005930", "quantity": 10, "average_price": 100.0}]),
        volatility_index=idx[["date", "value"]].copy(),
    )
    sigs = strat.generate_signals(ctx)
    sells = [s for s in sigs if s.side == "sell"]
    assert sells
    assert sells[0].reason == "time_exit_next_morning"


def test_intraday_state_roll_preserves_carry(tmp_path: Path) -> None:
    p = tmp_path / "fb_state.json"
    st = IntradayPaperState(day_kst="20260101", final_betting_carry={"positions": {"000660": {"x": 1}}})
    store = IntradayPaperStateStore(p, logger=None)
    store.save(st)
    loaded = store.load()
    assert "positions" in (loaded.final_betting_carry or {})
