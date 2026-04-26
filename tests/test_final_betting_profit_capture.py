from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.config import get_settings
from app.strategy.base_strategy import StrategyContext
from app.strategy.final_betting_v1_strategy import FinalBettingV1Strategy, set_final_betting_debug_now
from app.strategy.intraday_paper_state import IntradayPaperState

_KST = ZoneInfo("Asia/Seoul")


def _bars(symbol: str, ymd: str, *, open_px: float, closes: list[float]) -> pd.DataFrame:
    day = datetime.strptime(ymd, "%Y%m%d").replace(tzinfo=_KST)
    rows = []
    px = float(open_px)
    for i, c in enumerate(closes):
        ts = day.replace(hour=9, minute=0) + pd.Timedelta(minutes=i)
        o = px
        close = float(c)
        hi = max(o, close) * 1.001
        lo = min(o, close) * 0.999
        rows.append(
            {
                "symbol": symbol,
                "date": ts,
                "open": o,
                "high": hi,
                "low": lo,
                "close": close,
                "volume": 50_000.0,
            }
        )
        px = close
    return pd.DataFrame(rows)


def _ctx(prices: pd.DataFrame, *, symbol: str, qty: int, avg: float) -> StrategyContext:
    idx = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=200, freq="D", tz=_KST),
            "close": [100.0] * 200,
            "value": [18.0] * 200,
        }
    )
    return StrategyContext(
        prices=prices,
        kospi_index=idx[["date", "close"]].copy(),
        sp500_index=idx[["date", "close"]].copy(),
        portfolio=pd.DataFrame([{"symbol": symbol, "quantity": qty, "average_price": avg, "hold_days": 0}]),
        volatility_index=idx[["date", "value"]].copy(),
    )


def _make_carry(*, symbol: str, entry_day: str, ref_close: float, shares: int, partial_done: bool, ledger: list[dict] | None = None):
    carry = {
        "positions": {symbol: {"entry_kst_date": entry_day, "ref_close": ref_close, "shares": shares, "partial_scaleout_done": partial_done}},
    }
    if ledger is not None:
        carry["fb_perf_ledger"] = ledger
    return carry


def test_gap_up_no_longer_forces_full_exit_strong_followthrough(monkeypatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    sym = "005930"
    ref_close = 100.0
    open_px = 102.0
    df = _bars(sym, "20260417", open_px=open_px, closes=[102.1] * 20 + [102.6] * 5)

    st = IntradayPaperState(day_kst="20260417")
    st.final_betting_carry = _make_carry(symbol=sym, entry_day="20260416", ref_close=ref_close, shares=100, partial_done=False)

    strat = FinalBettingV1Strategy()
    strat.intraday_state = st
    strat.intraday_session_context = {"krx_session_state": "regular"}
    set_final_betting_debug_now(datetime(2026, 4, 17, 9, 15, tzinfo=_KST))
    sigs = strat.generate_signals(_ctx(df, symbol=sym, qty=100, avg=ref_close))
    sells = [s for s in sigs if s.side == "sell"]
    assert sells, sigs
    assert any("gap_up_take_profit" in s.reason for s in sells)
    assert sells[0].quantity < 100
    intents = list(strat.last_intraday_signal_breakdown.get("final_betting_exit_intents") or [])
    assert intents and intents[0].get("gap_up_scaleout_pct") is not None
    assert int(intents[0].get("runner_qty") or 0) > 0


def test_partial_done_runner_can_hold_on_strong_followthrough(monkeypatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    sym = "005930"
    ref_close = 100.0
    open_px = 102.0
    df = _bars(sym, "20260417", open_px=open_px, closes=[102.2] * 30)

    st = IntradayPaperState(day_kst="20260417")
    st.final_betting_carry = _make_carry(symbol=sym, entry_day="20260416", ref_close=ref_close, shares=60, partial_done=True)

    strat = FinalBettingV1Strategy()
    strat.intraday_state = st
    strat.intraday_session_context = {"krx_session_state": "regular"}
    set_final_betting_debug_now(datetime(2026, 4, 17, 9, 20, tzinfo=_KST))
    sigs = strat.generate_signals(_ctx(df, symbol=sym, qty=60, avg=ref_close))
    assert all(s.side != "sell" for s in sigs), sigs


def test_runner_followthrough_fail_exits_quickly(monkeypatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    sym = "005930"
    ref_close = 100.0
    open_px = 102.0
    df = _bars(sym, "20260417", open_px=open_px, closes=[102.0, 101.8, 101.0, 100.2, 99.4, 99.1, 99.0, 98.8, 98.7, 98.6, 98.5, 98.4, 98.3])

    st = IntradayPaperState(day_kst="20260417")
    st.final_betting_carry = _make_carry(symbol=sym, entry_day="20260416", ref_close=ref_close, shares=60, partial_done=True)

    strat = FinalBettingV1Strategy()
    strat.intraday_state = st
    strat.intraday_session_context = {"krx_session_state": "regular"}
    set_final_betting_debug_now(datetime(2026, 4, 17, 9, 18, tzinfo=_KST))
    sigs = strat.generate_signals(_ctx(df, symbol=sym, qty=60, avg=ref_close))
    sells = [s for s in sigs if s.side == "sell"]
    assert sells
    assert sells[0].quantity == 60


def test_gap_down_stop_still_full_exit(monkeypatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    sym = "005930"
    ref_close = 100.0
    open_px = 97.0
    df = _bars(sym, "20260417", open_px=open_px, closes=[97.0] * 12)

    st = IntradayPaperState(day_kst="20260417")
    st.final_betting_carry = _make_carry(symbol=sym, entry_day="20260416", ref_close=ref_close, shares=50, partial_done=False)

    strat = FinalBettingV1Strategy()
    strat.intraday_state = st
    strat.intraday_session_context = {"krx_session_state": "regular"}
    set_final_betting_debug_now(datetime(2026, 4, 17, 9, 6, tzinfo=_KST))
    sigs = strat.generate_signals(_ctx(df, symbol=sym, qty=50, avg=ref_close))
    sells = [s for s in sigs if s.side == "sell"]
    assert sells and sells[0].quantity == 50
    assert sells[0].reason == "gap_down_stop_atr_delayed"


def test_hard_exit_deadline_still_full_exit(monkeypatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    sym = "005930"
    ref_close = 100.0
    open_px = 100.8
    df = _bars(sym, "20260417", open_px=open_px, closes=[101.5] * 150)

    st = IntradayPaperState(day_kst="20260417")
    st.final_betting_carry = _make_carry(symbol=sym, entry_day="20260416", ref_close=ref_close, shares=10, partial_done=True)

    strat = FinalBettingV1Strategy()
    strat.intraday_state = st
    strat.intraday_session_context = {"krx_session_state": "regular"}
    set_final_betting_debug_now(datetime(2026, 4, 17, 11, 1, tzinfo=_KST))
    sigs = strat.generate_signals(_ctx(df, symbol=sym, qty=10, avg=ref_close))
    sells = [s for s in sigs if s.side == "sell"]
    assert sells and sells[0].quantity == 10
    assert sells[0].reason == "hard_exit_1100"


def test_aggressive_mode_keeps_larger_runner_than_defensive(monkeypatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    sym = "005930"
    ref_close = 100.0
    open_px = 102.0
    df = _bars(sym, "20260417", open_px=open_px, closes=[102.2] * 20)

    st_a = IntradayPaperState(day_kst="20260417")
    st_a.final_betting_carry = _make_carry(symbol=sym, entry_day="20260416", ref_close=ref_close, shares=100, partial_done=False)
    st_d = IntradayPaperState(day_kst="20260417")
    st_d.final_betting_carry = _make_carry(symbol=sym, entry_day="20260416", ref_close=ref_close, shares=100, partial_done=False)

    set_final_betting_debug_now(datetime(2026, 4, 17, 9, 15, tzinfo=_KST))
    strat_a = FinalBettingV1Strategy()
    strat_a.intraday_state = st_a
    strat_a.intraday_session_context = {"krx_session_state": "regular"}
    setattr(strat_a, "_paper_market_mode_snapshot", {"market_mode_active": True, "auto_market_mode": "aggressive"})
    sa = [s for s in strat_a.generate_signals(_ctx(df, symbol=sym, qty=100, avg=ref_close)) if s.side == "sell"][0]

    strat_d = FinalBettingV1Strategy()
    strat_d.intraday_state = st_d
    strat_d.intraday_session_context = {"krx_session_state": "regular"}
    setattr(strat_d, "_paper_market_mode_snapshot", {"market_mode_active": True, "auto_market_mode": "defensive"})
    sd = [s for s in strat_d.generate_signals(_ctx(df, symbol=sym, qty=100, avg=ref_close)) if s.side == "sell"][0]

    assert sa.quantity < sd.quantity


def test_profit_capture_profile_uses_ledger_health(monkeypatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    sym = "005930"
    ref_close = 100.0
    open_px = 102.0
    df = _bars(sym, "20260417", open_px=open_px, closes=[102.2] * 20)

    strong_ledger = [{"pnl_krw": 1000.0}] * 6 + [{"pnl_krw": -500.0}] * 4
    weak_ledger = [{"pnl_krw": -1000.0}] * 10

    set_final_betting_debug_now(datetime(2026, 4, 17, 9, 15, tzinfo=_KST))
    strat_s = FinalBettingV1Strategy()
    st_s = IntradayPaperState(day_kst="20260417")
    st_s.final_betting_carry = _make_carry(symbol=sym, entry_day="20260416", ref_close=ref_close, shares=100, partial_done=False, ledger=strong_ledger)
    strat_s.intraday_state = st_s
    strat_s.intraday_session_context = {"krx_session_state": "regular"}
    sigs_s = strat_s.generate_signals(_ctx(df, symbol=sym, qty=100, avg=ref_close))
    _ = sigs_s
    intent_s = list(strat_s.last_intraday_signal_breakdown.get("final_betting_exit_intents") or [])[0]

    strat_w = FinalBettingV1Strategy()
    st_w = IntradayPaperState(day_kst="20260417")
    st_w.final_betting_carry = _make_carry(symbol=sym, entry_day="20260416", ref_close=ref_close, shares=100, partial_done=False, ledger=weak_ledger)
    strat_w.intraday_state = st_w
    strat_w.intraday_session_context = {"krx_session_state": "regular"}
    sigs_w = strat_w.generate_signals(_ctx(df, symbol=sym, qty=100, avg=ref_close))
    _ = sigs_w
    intent_w = list(strat_w.last_intraday_signal_breakdown.get("final_betting_exit_intents") or [])[0]

    assert float(intent_w.get("gap_up_scaleout_pct") or 0.0) > float(intent_s.get("gap_up_scaleout_pct") or 0.0)
    assert intent_w.get("fb_profit_capture_profile")

