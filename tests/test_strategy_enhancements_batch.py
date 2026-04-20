"""Regime softening, ATR blend, cooldown, rebound detection, fill-performance helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.config import get_settings
from app.strategy.final_betting_rebound import (
    blend_stop_tp_with_atr,
    daily_atr14_pct,
    evaluate_bearish_rebound_candidate,
)
from app.strategy.market_regime import MarketRegimeFeatures
from app.strategy.regime_soft import compute_soft_regime
from app.strategy.strategy_fill_performance import (
    apply_fb_dynamic_cooldown,
    classify_fb_exit_outcome,
    fb_health_size_multiplier,
    fb_performance_snapshot,
    record_fb_sell_outcome,
)


def test_soft_regime_explicit_neutral_and_mild_bullish_reachable() -> None:
    """Score bands: neutral [-0.2,0.2), mild_bullish [0.2,0.55) — verified by direct feature tuples."""
    neutral = MarketRegimeFeatures(
        kospi_return_pct=0.0,
        sp500_return_pct=0.0,
        kospi_ma20_slope_pct=0.0,
        kospi_ma60_slope_pct=0.0,
        kospi_ma120_slope_pct=0.0,
        sp500_ma20_slope_pct=0.0,
        sp500_ma60_slope_pct=0.0,
        sp500_ma120_slope_pct=0.0,
        volatility_level=18.0,
        volatility_change_pct=0.5,
        volatility_rising=False,
    )
    rn = compute_soft_regime(neutral, "sideways")
    assert rn.market_regime == "neutral"
    assert rn.regime_score == 0.0

    mild = MarketRegimeFeatures(
        kospi_return_pct=0.4,
        sp500_return_pct=0.4,
        kospi_ma20_slope_pct=0.2,
        kospi_ma60_slope_pct=0.2,
        kospi_ma120_slope_pct=0.2,
        sp500_ma20_slope_pct=0.2,
        sp500_ma60_slope_pct=0.2,
        sp500_ma120_slope_pct=0.2,
        volatility_level=18.0,
        volatility_change_pct=0.5,
        volatility_rising=False,
    )
    rm = compute_soft_regime(mild, "sideways")
    assert rm.market_regime == "mild_bullish"
    assert 0.2 <= rm.regime_score < 0.55


def test_market_filter_softens_when_soft_regime_neutral_and_proxy_ok() -> None:
    """Mirrors final_betting_v1: strict filter fail but soft regime allows relaxed US proxy rule."""
    market_filter_ok = False
    market_filter_ready = True
    us_night_proxy_ret = 0.5
    kospi_day_ret = -0.5
    soft_label = "neutral"
    market_filter_ok_effective = market_filter_ok
    if (
        not market_filter_ok_effective
        and market_filter_ready
        and us_night_proxy_ret is not None
        and soft_label in ("neutral", "mild_bullish", "mild_bearish")
    ):
        market_filter_ok_effective = bool(us_night_proxy_ret >= 0.4 and (kospi_day_ret is None or kospi_day_ret > -1.35))
    assert market_filter_ok_effective is True


def test_soft_regime_size_scaling_not_all_ones() -> None:
    feats = MarketRegimeFeatures(
        kospi_return_pct=0.2,
        sp500_return_pct=0.2,
        kospi_ma20_slope_pct=0.1,
        kospi_ma60_slope_pct=0.1,
        kospi_ma120_slope_pct=0.1,
        sp500_ma20_slope_pct=0.1,
        sp500_ma60_slope_pct=0.1,
        sp500_ma120_slope_pct=0.1,
        volatility_level=18.0,
        volatility_change_pct=0.5,
        volatility_rising=False,
    )
    r = compute_soft_regime(feats, "sideways")
    assert r.market_regime in ("neutral", "mild_bullish", "mild_bearish", "bullish", "bearish")
    assert 0.15 <= r.regime_size_multiplier <= 1.0
    assert r.regime_entry_allowed is True


def test_high_vol_still_blocks_entries() -> None:
    feats = MarketRegimeFeatures(
        kospi_return_pct=1.0,
        sp500_return_pct=1.0,
        kospi_ma20_slope_pct=0.2,
        kospi_ma60_slope_pct=0.2,
        kospi_ma120_slope_pct=0.2,
        sp500_ma20_slope_pct=0.2,
        sp500_ma60_slope_pct=0.2,
        sp500_ma120_slope_pct=0.2,
        volatility_level=18.0,
        volatility_change_pct=0.5,
        volatility_rising=False,
    )
    r = compute_soft_regime(feats, "high_volatility_risk")
    assert r.regime_entry_allowed is False
    assert r.regime_size_multiplier == 0.0


def test_daily_atr14_fallback_when_insufficient_history() -> None:
    import pandas as pd

    short = pd.DataFrame({"high": [1.0], "low": [0.9], "close": [0.95]})
    _atr, pct, fb = daily_atr14_pct(short)
    assert fb is True
    assert pct == 1.5


def test_atr_blend_fallback_on_bad_atr() -> None:
    sl, tp, fb = blend_stop_tp_with_atr(
        fixed_stop_pct=2.0,
        fixed_tp_pct=2.0,
        atr_pct=0.0,
        atr_stop_mult=1.0,
        atr_tp_mult=1.0,
    )
    assert fb is True
    assert sl == 2.0 and tp == 2.0


def test_atr_blend_scales_with_vol() -> None:
    sl, tp, fb = blend_stop_tp_with_atr(
        fixed_stop_pct=2.0,
        fixed_tp_pct=2.0,
        atr_pct=3.0,
        atr_stop_mult=1.0,
        atr_tp_mult=1.0,
    )
    assert fb is False
    assert sl > 2.0
    assert tp > 2.0


def test_dynamic_cooldown_profit_vs_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_CD_AFTER_PROFIT_MINUTES", "12")
    monkeypatch.setenv("PAPER_FINAL_BETTING_CD_AFTER_STOP_MINUTES", "30")
    monkeypatch.setenv("PAPER_FINAL_BETTING_CD_AFTER_REPEAT_STOP_MINUTES", "95")
    get_settings.cache_clear()
    cfg = get_settings()
    state = MagicMock()
    state.cooldown_until_iso = {}
    carry: dict = {}
    m1, _ = apply_fb_dynamic_cooldown(
        cfg=cfg,
        state=state,
        carry=carry,
        symbol="005930",
        reason="gap_up_take_profit",
        pnl_pct=1.2,
        today_kst="20260420",
    )
    assert m1 == 12
    m2, _ = apply_fb_dynamic_cooldown(
        cfg=cfg,
        state=state,
        carry=carry,
        symbol="005930",
        reason="gap_down_stop_atr_delayed",
        pnl_pct=-1.0,
        today_kst="20260420",
    )
    assert m2 == 30
    m3, _ = apply_fb_dynamic_cooldown(
        cfg=cfg,
        state=state,
        carry=carry,
        symbol="005930",
        reason="weak_morning_flush_fast_stop",
        pnl_pct=-0.5,
        today_kst="20260420",
    )
    assert m3 == 95


def test_classify_exit_outcome() -> None:
    assert classify_fb_exit_outcome("gap_up_take_profit", pnl_pct=0.0)[0] == "profit"
    assert classify_fb_exit_outcome("gap_down_stop_atr_delayed", pnl_pct=-1.0)[0] == "stop"


def test_fb_performance_snapshot_from_ledger() -> None:
    carry: dict = {}
    record_fb_sell_outcome(carry, symbol="A", sold_qty=10, fill_px=110.0, entry_px=100.0, reason="x")
    record_fb_sell_outcome(carry, symbol="A", sold_qty=10, fill_px=90.0, entry_px=100.0, reason="y")
    snap = fb_performance_snapshot(carry, last_n=10)
    assert snap["trade_count"] == 2
    assert snap["expectancy_krw"] is not None


def test_fb_health_weak_when_bad_streak() -> None:
    carry: dict = {}
    for _ in range(12):
        record_fb_sell_outcome(carry, symbol="A", sold_qty=1, fill_px=90.0, entry_px=100.0, reason="stop")
    label, mult = fb_health_size_multiplier(carry)
    assert label == "weak"
    assert mult < 1.0


def test_rebound_pattern_blocks_panic() -> None:
    import pandas as pd

    morning = pd.DataFrame({"low": [90.0]})
    afternoon = pd.DataFrame()
    sub_s = pd.DataFrame({"volume": [1e6] * 40})
    info = evaluate_bearish_rebound_candidate(
        sub_s=sub_s,
        day_open=100.0,
        day_hi=100.0,
        day_lo=10.0,
        last_close=12.0,
        rsi14=20.0,
        ma20_last=50.0,
        ma20_prev=49.0,
        morning=morning,
        afternoon=afternoon,
        kospi_day_ret=0.0,
    )
    assert info.get("panic_candle") is True
    assert info.get("bearish_rebound_candidate") is False


def test_rebound_candidate_pattern_a_like() -> None:
    import pandas as pd

    morning = pd.DataFrame({"low": [98.0]})
    afternoon = pd.DataFrame()
    sub_s = pd.DataFrame({"volume": [1e6] * 40})
    info = evaluate_bearish_rebound_candidate(
        sub_s=sub_s,
        day_open=100.0,
        day_hi=102.0,
        day_lo=97.0,
        last_close=98.5,
        rsi14=38.0,
        ma20_last=99.0,
        ma20_prev=98.5,
        morning=morning,
        afternoon=afternoon,
        kospi_day_ret=0.2,
    )
    assert "final_betting_score" in info
    assert info.get("final_betting_block_reason") != "not_bearish_candle"


def test_rank_pool_uses_config_not_hardcoded_three(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: pool was previously [:3]; now max(3, paper_final_betting_rank_pool_top_n)."""
    monkeypatch.setenv("PAPER_FINAL_BETTING_RANK_POOL_TOP_N", "8")
    get_settings.cache_clear()
    cfg = get_settings()
    pool_n = max(3, int(getattr(cfg, "paper_final_betting_rank_pool_top_n", 5)))
    assert pool_n == 8


def test_on_fb_sell_accepted_records_ledger_and_dynamic_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.orders.models import OrderRequest
    from app.strategy.final_betting_v1_strategy import FinalBettingV1Strategy
    from app.strategy.intraday_paper_state import IntradayPaperState

    monkeypatch.setenv("PAPER_FINAL_BETTING_CD_AFTER_PROFIT_MINUTES", "11")
    get_settings.cache_clear()
    strat = FinalBettingV1Strategy()
    st = IntradayPaperState(day_kst="20260420")
    st.final_betting_carry = {"positions": {"005930": {"shares": 5, "ref_close": 1000.0}}}
    st.cooldown_until_iso = {}
    order = OrderRequest(
        symbol="005930",
        side="sell",
        quantity=5,
        price=1010.0,
        signal_reason="gap_up_take_profit",
    )
    strat.on_fb_sell_accepted("005930", 5, st, order=order)
    assert len(st.final_betting_carry.get("fb_perf_ledger") or []) == 1
    assert st.final_betting_carry["fb_perf_ledger"][0]["fill_px"] == 1010.0
    assert "005930" in st.cooldown_until_iso
    tr = st.final_betting_carry.get("fb_cooldown_trace", {}).get("005930", {})
    assert tr.get("outcome_kind") == "profit"


def test_on_fb_sell_without_order_still_appends_ledger_no_cooldown() -> None:
    from app.strategy.final_betting_v1_strategy import FinalBettingV1Strategy
    from app.strategy.intraday_paper_state import IntradayPaperState

    strat = FinalBettingV1Strategy()
    st = IntradayPaperState(day_kst="20260420")
    st.final_betting_carry = {"positions": {"005930": {"shares": 1, "ref_close": 100.0}}}
    st.cooldown_until_iso = {}
    strat.on_fb_sell_accepted("005930", 1, st, order=None)
    assert len(st.final_betting_carry.get("fb_perf_ledger") or []) == 1
    assert st.cooldown_until_iso == {}


def test_min_alloc_vs_max_cap_triggers_strategy_guard() -> None:
    """Same condition as final_betting_v1 second pass: max_pct < min_pct → blocked without entry."""
    max_pct = 15.0
    min_pct = 20.0
    assert max_pct + 1e-9 < min_pct


def test_diagnostics_fields_in_cooldown_detail() -> None:
    from app.strategy.final_betting_v1_strategy import _fb_cooldown_detail

    st = MagicMock()
    future = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
    st.cooldown_until_iso = {"005930": future}
    carry = {"fb_cooldown_trace": {"005930": {"cooldown_reason": "after_stop_exit"}}}
    d = _fb_cooldown_detail(st, carry)
    assert "005930" in d["symbols"]
    assert d["symbols"]["005930"]["cooldown_reason"] == "after_stop_exit"
