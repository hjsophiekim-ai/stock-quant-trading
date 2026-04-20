"""
Strategy-level Paper market mode: inject bundle via attach_market_mode_to_strategy
and assert mode-dependent outcomes inside generate_signals (not policy helpers alone).
"""

from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.config import get_settings
from app.brokers.paper_broker import PaperBroker
from app.scheduler.intraday_jobs import IntradaySchedulerJobs
from app.strategy.base_strategy import StrategyContext
from app.strategy.final_betting_v1_strategy import FinalBettingV1Strategy, set_final_betting_debug_now
from app.strategy.intraday_common import IntradaySessionSnapshot
from app.strategy.intraday_paper_state import IntradayPaperState
from app.strategy.market_mode_engine import attach_market_mode_to_strategy
from app.strategy.scalp_macd_rsi_3m_v1_strategy import ScalpMacdRsi3mV1Strategy
from app.strategy.scalp_rsi_flag_hf_v1_strategy import ScalpRsiFlagHfV1Strategy
from app.strategy.swing_relaxed_v2_strategy import SwingRelaxedV2Strategy

_KST = ZoneInfo("Asia/Seoul")


def _idx_pair(*, kospi_last_pct: float, sp500_last_pct: float, n: int = 30) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tail two closes set _index_day_return_pct to ~kospi_last_pct / sp500_last_pct."""
    dates = pd.date_range("2026-04-14", periods=n, freq="D", tz=_KST)
    kprev = 2500.0
    kcur = kprev * (1.0 + kospi_last_pct / 100.0)
    kcloses = [kprev + (kcur - kprev) * i / (n - 1) for i in range(n)]
    kcloses[-2] = kprev
    kcloses[-1] = kcur
    kdf = pd.DataFrame({"date": dates, "close": kcloses})

    sprev = 4500.0
    scur = sprev * (1.0 + sp500_last_pct / 100.0)
    scloses = [sprev + (scur - sprev) * i / (n - 1) for i in range(n)]
    scloses[-2] = sprev
    scloses[-1] = scur
    sdf = pd.DataFrame({"date": dates, "close": scloses})
    return kdf, sdf


def _vol_df(kdf: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"date": kdf["date"], "value": [16.0] * len(kdf)})


def _fb_minute_bars() -> pd.DataFrame:
    day = datetime(2026, 4, 16, tzinfo=_KST)
    rows = []
    px = 100.0
    for i in range(380):
        ts = day.replace(hour=9, minute=0) + pd.Timedelta(minutes=i)
        if ts.hour == 15 and ts.minute > 20:
            break
        o, h, low, c = px, px + 0.15, px - 0.05, px + 0.08
        rows.append(
            {
                "symbol": "005930",
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


def test_final_betting_v1_mode_injection_market_filter_and_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same StrategyContext: neutral vs aggressive — effective mins differ; overlay when aggressive + strong KOSPI day."""
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    cfg = get_settings()
    kdf, sdf = _idx_pair(kospi_last_pct=1.5, sp500_last_pct=0.45)
    vol = _vol_df(kdf)
    px = _fb_minute_bars()
    ctx = StrategyContext(
        prices=px,
        kospi_index=kdf,
        sp500_index=sdf,
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
        volatility_index=vol,
    )
    monkeypatch.setattr(
        "app.strategy.final_betting_v1_strategy.classify_market_regime",
        lambda *a, **k: SimpleNamespace(regime="bearish_trend", features=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "app.strategy.final_betting_v1_strategy.compute_soft_regime",
        lambda *_a, **_k: SimpleNamespace(
            market_regime="bearish_trend",
            regime_score=0.0,
            regime_entry_allowed=True,
            regime_size_multiplier=1.0,
            regime_block_reason="",
        ),
    )

    set_final_betting_debug_now(datetime(2026, 4, 16, 15, 12, tzinfo=_KST))

    def run_once(manual: str) -> dict:
        st = FinalBettingV1Strategy()
        st.intraday_state = IntradayPaperState(day_kst="20260416")
        st.intraday_session_context = {"krx_session_state": "regular"}
        attach_market_mode_to_strategy(
            st,
            manual=manual,
            kospi=kdf,
            sp500=sdf,
            volatility=vol,
            settings=cfg,
        )
        st.generate_signals(ctx)
        return dict(st.last_intraday_signal_breakdown.get("market_filter") or {})

    mf_n = run_once("neutral")
    mf_a = run_once("aggressive")

    assert mf_n["market_mode_active"] == "neutral"
    assert mf_a["market_mode_active"] == "aggressive"
    assert mf_a["effective_kospi_day_ret_hard_min"] < mf_n["effective_kospi_day_ret_hard_min"]
    assert mf_a["effective_us_night_hard_min"] < mf_n["effective_us_night_hard_min"]
    assert mf_a["effective_kospi_day_ret_soft_min"] < mf_n["effective_kospi_day_ret_soft_min"]
    assert mf_a["effective_us_night_soft_min"] < mf_n["effective_us_night_soft_min"]
    assert mf_n["market_filter_ok"] is False
    assert mf_a["market_filter_ok"] is True
    assert mf_a["aggressive_kospi_tape_overlay"]["tape_overlay_applied"] is True
    assert mf_a["aggressive_kospi_tape_overlay"]["tape_tier"] == "strong"
    assert mf_n["aggressive_kospi_tape_overlay"]["tape_overlay_applied"] is False


def test_scalp_rsi_flag_hf_v1_mode_injection_path_hits_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Neutral: rsi_red_path_hits=1, min_path=2 -> path_hits_lt_min(1<2).
    Aggressive: min_path=1 -> reversal path passes; buy after mocked gates.
    """
    get_settings.cache_clear()
    cfg = get_settings()
    kdf, sdf = _idx_pair(kospi_last_pct=0.2, sp500_last_pct=0.2)
    vol = _vol_df(kdf)
    base = pd.Timestamp("2026-04-18 10:30:00", tz=_KST)
    rows = []
    price = 50000.0
    for i in range(40):
        rows.append(
            {
                "symbol": "005930",
                "date": base + pd.Timedelta(minutes=3 * i),
                "open": price * 0.999,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": 2_000_000.0,
            }
        )
        price *= 1.0005
    px = pd.DataFrame(rows)
    ctx = StrategyContext(
        prices=px,
        kospi_index=kdf,
        sp500_index=sdf,
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]),
        volatility_index=vol,
    )

    monkeypatch.setattr(
        "app.strategy.scalp_rsi_flag_hf_v1_strategy.classify_market_regime",
        lambda *a, **k: SimpleNamespace(regime="bullish_trend"),
    )
    monkeypatch.setattr("app.strategy.scalp_rsi_flag_hf_v1_strategy.get_krx_session_state_kst", lambda *a, **k: "regular")
    monkeypatch.setattr(
        "app.strategy.scalp_rsi_flag_hf_v1_strategy.should_force_flatten_before_close_kst",
        lambda **_: False,
    )
    monkeypatch.setattr("app.strategy.scalp_rsi_flag_hf_v1_strategy.last_bar_body_pct", lambda _df: 0.01)

    def fake_red(*_a, **_k):
        return {
            "rsi_red_flag_buy": True,
            "rsi_red_flag_reason": "test",
            "rsi_red_path_hits": 1,
            "rsi_red_core_ok": True,
            "volume_confirmation_ok": True,
            "volume_confirmation_value": 1.0,
            "volume_confirmation_threshold": 0.0,
            "volume_ratio_vs_ma": 1.0,
            "volume_confirmation_ratio_floor": 0.0,
            "volume_confirmation_detail": "",
            "strong_override_used": False,
        }

    def fake_mom(*_a, **_k):
        return {
            "momentum_continuation_ok": False,
            "momentum_path_hits": 0,
            "momentum_continuation_reason": "test_off",
            "momentum_paths_detail": "",
            "trend_strength_score": 0.0,
            "continuation_quality_score": 50.0,
            "strong_override_used": False,
        }

    monkeypatch.setattr("app.strategy.scalp_rsi_flag_hf_v1_strategy.rsi_red_flag_buy", fake_red)
    monkeypatch.setattr(
        "app.strategy.scalp_rsi_flag_hf_v1_strategy.evaluate_momentum_continuation_entry",
        fake_mom,
    )
    monkeypatch.setattr(
        "app.strategy.intraday_entry_qty.resolved_intraday_entry_quantity",
        lambda *_a, **_k: 1,
    )

    quote = {
        "005930": {
            "output": {
                "acml_vol": 80_000_000.0,
                "acml_tr_pbmn": 8_000_000_000_000.0,
                "bidp": 49990.0,
                "askp": 50010.0,
            }
        }
    }

    def run_rsi(manual: str) -> tuple[list, dict, dict]:
        st = ScalpRsiFlagHfV1Strategy()
        st.intraday_state = IntradayPaperState(day_kst="20260418")
        st.intraday_session_context = {"krx_session_state": "regular"}
        st.quote_by_symbol = quote
        attach_market_mode_to_strategy(
            st,
            manual=manual,
            kospi=kdf,
            sp500=sdf,
            volatility=vol,
            settings=cfg,
        )
        sigs = st.generate_signals(ctx)
        mm = dict(st.last_intraday_signal_breakdown.get("market_mode") or {})
        diag = st.last_diagnostics[-1] if st.last_diagnostics else {}
        return sigs, mm, diag

    sigs_n, mm_n, d_n = run_rsi("neutral")
    sigs_a, mm_a, d_a = run_rsi("aggressive")

    assert mm_n.get("market_mode_active") == "neutral"
    assert mm_a.get("market_mode_active") == "aggressive"
    assert not sigs_n
    assert d_n.get("blocked_reason") == "path_hits_lt_min(1<2)"
    assert int(d_n.get("min_required_reversal_hits") or 0) == 2
    assert int(d_a.get("min_required_reversal_hits") or 0) == 1
    assert d_a.get("entered") is True
    assert any(s.side == "buy" for s in sigs_a)


def test_scalp_macd_rsi_3m_v1_mode_injection_macd_hits_required(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    cfg = get_settings()
    kdf, sdf = _idx_pair(kospi_last_pct=0.1, sp500_last_pct=0.1)
    vol = _vol_df(kdf)
    base = pd.Timestamp("2026-04-18 10:30:00", tz=_KST)
    rows = []
    p = 50000.0
    for i in range(45):
        rows.append(
            {
                "symbol": "005930",
                "date": base + pd.Timedelta(minutes=3 * i),
                "open": p * 0.999,
                "high": p * 1.002,
                "low": p * 0.998,
                "close": p,
                "volume": 2_000_000.0 + i * 10_000,
            }
        )
        p *= 1.001
    px = pd.DataFrame(rows)
    ctx = StrategyContext(
        prices=px,
        kospi_index=kdf,
        sp500_index=sdf,
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]),
        volatility_index=vol,
    )
    monkeypatch.setattr(
        "app.strategy.scalp_macd_rsi_3m_v1_strategy.classify_market_regime",
        lambda *a, **k: SimpleNamespace(regime="bullish_trend"),
    )
    monkeypatch.setattr(
        "app.strategy.scalp_macd_rsi_3m_v1_strategy.minutes_since_session_open_kst",
        lambda **_: 45.0,
    )
    monkeypatch.setattr(
        "app.strategy.scalp_macd_rsi_3m_v1_strategy.minutes_to_regular_close_kst",
        lambda **_: 120.0,
    )
    monkeypatch.setattr(
        "app.strategy.scalp_macd_rsi_3m_v1_strategy.should_force_flatten_before_close_kst",
        lambda **_: False,
    )

    def run_macd(manual: str) -> dict:
        st = ScalpMacdRsi3mV1Strategy()
        st.intraday_session_context = {"krx_session_state": "regular"}
        attach_market_mode_to_strategy(st, manual=manual, kospi=kdf, sp500=sdf, volatility=vol, settings=cfg)
        st.generate_signals(ctx)
        return dict(st.last_intraday_signal_breakdown)

    br_n = run_macd("neutral")
    br_a = run_macd("aggressive")
    assert br_n.get("macd_core_hits_required") == 4
    assert br_a.get("macd_core_hits_required") == 3
    mm_n = br_n.get("market_mode") or {}
    mm_a = br_a.get("market_mode") or {}
    assert mm_n.get("market_mode_active") == "neutral"
    assert mm_a.get("market_mode_active") == "aggressive"


def test_swing_relaxed_v2_mode_injection_min_hits_in_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive raises min_hits_eff (4중3) vs neutral (4중2) — same prices, mode-only change."""
    get_settings.cache_clear()
    cfg = get_settings()
    kdf, sdf = _idx_pair(kospi_last_pct=0.3, sp500_last_pct=0.3)
    vol = _vol_df(kdf)
    dates = pd.date_range("2026-02-01", periods=130, freq="D", tz=_KST)
    sym_rows = []
    for sym, mul in (("AAA", 1.0), ("BBB", 1.01), ("CCC", 1.02), ("DDD", 1.03), ("EEE", 1.04), ("FFF", 1.05), ("GGG", 1.06), ("HHH", 1.07)):
        base = 100.0 * mul
        for i, d in enumerate(dates):
            c = base * (1.0 + 0.001 * i)
            sym_rows.append(
                {
                    "symbol": sym,
                    "date": d,
                    "open": c * 0.99,
                    "high": c * 1.01,
                    "low": c * 0.98,
                    "close": c,
                    "volume": 1_000_000.0,
                }
            )
    prices = pd.DataFrame(sym_rows)
    ctx = StrategyContext(
        prices=prices,
        kospi_index=kdf,
        sp500_index=sdf,
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
        volatility_index=vol,
    )
    monkeypatch.setattr(
        "app.strategy.swing_relaxed_v2_strategy.classify_market_regime",
        lambda *a, **k: SimpleNamespace(regime="bullish_trend"),
    )
    monkeypatch.setattr(
        "app.strategy.swing_relaxed_v2_strategy.filter_relaxed_swing_candidates",
        lambda prices_df: sorted(prices_df["symbol"].unique().tolist()),  # noqa: ARG005
    )
    monkeypatch.setattr(
        "app.strategy.swing_relaxed_v2_strategy._swing_v2_liquidity_and_weak_bounce",
        lambda *a, **k: (True, "", {}),
    )

    def fake_should(*_a, min_hits: int = 2, rsi_max: float = 55.0, **_k):
        detail = {"trend_cond": False, "drop_cond": False, "rsi_cond": False, "rebound_cond": False}
        return (False, 0, detail)

    monkeypatch.setattr(
        "app.strategy.swing_relaxed_v2_strategy.should_enter_long_relaxed_v2",
        fake_should,
    )

    def first_v2_gate_line(manual: str) -> str:
        st = SwingRelaxedV2Strategy()
        attach_market_mode_to_strategy(st, manual=manual, kospi=kdf, sp500=sdf, volatility=vol, settings=cfg)
        st.generate_signals(ctx)
        for row in st.last_diagnostics or []:
            br = str(row.get("blocked_reason") or "")
            if re.search(r"4\uC911\d", br):
                return br
        return ""

    line_n = first_v2_gate_line("neutral")
    line_d = first_v2_gate_line("defensive")
    m_n = re.search(r"4\uC911(\d)", line_n)
    m_d = re.search(r"4\uC911(\d)", line_d)
    assert m_n and int(m_n.group(1)) == 2
    assert m_d and int(m_d.group(1)) == 3
    line_a = first_v2_gate_line("aggressive")
    assert "RSI>=58.0" in line_a or "RSI>=58" in line_a
    assert "RSI>=55.0" in line_n or "RSI>=55" in line_n
    assert "RSI>=58" not in line_n and "RSI>=58.0" not in line_n


def test_intraday_scheduler_tick_market_mode_propagation(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_intraday_cycle attaches mode; report includes bundle + strategy breakdown."""
    get_settings.cache_clear()
    cfg = get_settings()
    kdf, sdf = _idx_pair(kospi_last_pct=0.2, sp500_last_pct=0.2)
    vol = _vol_df(kdf)
    base = pd.Timestamp("2026-04-18 10:30:00", tz=_KST)
    rows = []
    p = 50000.0
    for i in range(35):
        rows.append(
            {
                "symbol": "005930",
                "date": base + pd.Timedelta(minutes=3 * i),
                "open": p * 0.999,
                "high": p * 1.002,
                "low": p * 0.998,
                "close": p,
                "volume": 3_000_000.0,
            }
        )
        p *= 1.0008
    universe = pd.DataFrame(rows)
    snap = IntradaySessionSnapshot(
        state="regular",
        fetch_allowed=True,
        order_allowed=True,
        fetch_block_reason="",
        order_block_reason="",
        regular_session_kst=True,
    )
    broker = PaperBroker(initial_cash=100_000_000.0)

    monkeypatch.setattr(
        "app.strategy.scalp_macd_rsi_3m_v1_strategy.classify_market_regime",
        lambda *a, **k: SimpleNamespace(regime="bullish_trend"),
    )
    monkeypatch.setattr(
        "app.strategy.scalp_macd_rsi_3m_v1_strategy.minutes_since_session_open_kst",
        lambda **_: 45.0,
    )
    monkeypatch.setattr(
        "app.strategy.scalp_macd_rsi_3m_v1_strategy.minutes_to_regular_close_kst",
        lambda **_: 120.0,
    )
    monkeypatch.setattr(
        "app.strategy.scalp_macd_rsi_3m_v1_strategy.should_force_flatten_before_close_kst",
        lambda **_: False,
    )

    def run_sched(manual: str) -> dict:
        strat = ScalpMacdRsi3mV1Strategy()
        jobs = IntradaySchedulerJobs(strategy=strat, broker=broker)
        return jobs.run_intraday_cycle(
            universe_tf=universe,
            kospi_index=kdf,
            sp500_index=sdf,
            timeframe="3m",
            quote_by_symbol={},
            forced_flatten=False,
            paper_trading_symbols_resolved=["005930"],
            intraday_bar_fetch_summary=[],
            intraday_universe_row_count=len(universe),
            regular_session_kst=True,
            intraday_session_snapshot=snap,
            paper_market_mode_manual=manual,
        )

    rep_n = run_sched("neutral")
    rep_a = run_sched("aggressive")
    assert rep_n["market_mode"]["manual_market_mode_override"] == "neutral"
    assert rep_n["market_mode"]["market_mode_active"] == "neutral"
    assert rep_a["market_mode"]["manual_market_mode_override"] == "aggressive"
    assert rep_a["market_mode"]["market_mode_active"] == "aggressive"
    assert rep_a["market_mode"]["market_mode_source"] == "manual_override"
    br_n = rep_n.get("intraday_signal_breakdown") or {}
    br_a = rep_a.get("intraday_signal_breakdown") or {}
    assert br_n.get("macd_core_hits_required") == 4
    assert br_a.get("macd_core_hits_required") == 3
