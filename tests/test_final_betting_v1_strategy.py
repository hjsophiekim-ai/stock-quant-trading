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
    apply_aggressive_kospi_tape_overlay,
    set_final_betting_debug_now,
)
from app.strategy.intraday_paper_state import IntradayPaperState, IntradayPaperStateStore

_KST = ZoneInfo("Asia/Seoul")


def _index_frame(n: int = 130) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=n, freq="D", tz=_KST),
            # final_betting_v1 시장필터(us_night_proxy>=+0.8%)를 통과하도록 일간 +1% 추세.
            "close": [100.0 * (1.01**i) for i in range(n)],
            "value": [15.0 + 0.01 * i for i in range(n)],
        }
    )


def test_calendar_days_between() -> None:
    assert _calendar_days_between("20260101", "20260103") == 2
    assert _calendar_days_between("20260103", "20260101") == 2


def test_apply_aggressive_kospi_tape_overlay_strong_day() -> None:
    us_h, kp_h, us_s, kp_s = 0.52, -1.35, 0.28, -1.55
    nu_h, nk_h, nu_s, nk_s, diag = apply_aggressive_kospi_tape_overlay(
        market_mode_active="aggressive",
        kospi_day_ret_pct=1.4,
        us_h=us_h,
        kp_h=kp_h,
        us_s=us_s,
        kp_s=kp_s,
    )
    assert diag["tape_overlay_applied"] is True
    assert diag["tape_tier"] == "strong"
    assert nu_h < us_h
    assert nk_h < kp_h
    assert nu_s < us_s
    assert nk_s < kp_s


def test_apply_aggressive_kospi_tape_overlay_skipped_for_neutral() -> None:
    _, _, _, _, diag = apply_aggressive_kospi_tape_overlay(
        market_mode_active="neutral",
        kospi_day_ret_pct=2.0,
        us_h=0.5,
        kp_h=-1.2,
        us_s=0.3,
        kp_s=-1.5,
    )
    assert diag["tape_overlay_applied"] is False


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
    assert sells[0].reason == "hard_exit_1100"


def test_overnight_exposure_guard_blocks_at_entry_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """carry 추적 포지션 노셔널이 평가금 대비 상한을 넘으면 신규 진입 차단."""
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    monkeypatch.setenv("PAPER_FINAL_BETTING_MAX_OVERNIGHT_EQUITY_PCT", "30")
    get_settings.cache_clear()
    strat = FinalBettingV1Strategy()
    setattr(strat, "_final_betting_equity_krw", 50_000_000.0)
    set_final_betting_debug_now(datetime(2026, 4, 16, 15, 12, tzinfo=_KST))
    st = IntradayPaperState(day_kst="20260416")
    st.final_betting_carry = {
        "positions": {
            "005930": {
                "entry_kst_date": "20260415",
                "ref_close": 70000.0,
                "shares": 700,
                "partial_scaleout_done": False,
            },
        },
    }
    strat.intraday_state = st
    strat.intraday_session_context = {"krx_session_state": "regular"}
    df = _minute_series("005930", "20260416")
    idx = _index_frame()
    ctx = StrategyContext(
        prices=df,
        kospi_index=idx[["date", "close"]].copy(),
        sp500_index=idx[["date", "close"]].copy(),
        portfolio=pd.DataFrame([{"symbol": "005930", "quantity": 700, "average_price": 70000.0}]),
        volatility_index=idx[["date", "value"]].copy(),
    )
    strat.generate_signals(ctx)
    assert strat.last_intraday_signal_breakdown.get("blocked") == "max_overnight_equity_pct"


def test_intraday_state_roll_preserves_carry(tmp_path: Path) -> None:
    p = tmp_path / "fb_state.json"
    st = IntradayPaperState(day_kst="20260101", final_betting_carry={"positions": {"000660": {"x": 1}}})
    store = IntradayPaperStateStore(p, logger=None)
    store.save(st)
    loaded = store.load()
    assert "positions" in (loaded.final_betting_carry or {})
