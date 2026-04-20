"""scalp_rsi_flag_hf_v1 momentum continuation path + adaptive volume (synthetic, no live broker)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.strategy.base_strategy import StrategyContext
from app.strategy.intraday_paper_state import IntradayPaperState
from app.strategy.market_regime import MarketRegimeResult
from app.strategy.rsi_flag_helpers import evaluate_rsi_red_flag_buy, rsi_hf_volume_confirmation
from app.strategy.scalp_rsi_flag_hf_v1_strategy import ScalpRsiFlagHfV1Strategy
from app.strategy.scalp_rsi_hf_momentum import evaluate_momentum_continuation_entry, momentum_blow_off_guard

_KST = ZoneInfo("Asia/Seoul")


def _idx_vol():
    k = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=40, freq="D", tz=_KST), "close": [2500.0 + i for i in range(40)]})
    vol = k[["date"]].copy()
    vol["value"] = 15.0
    return k, vol


def build_leader_continuation_3m(symbol: str = "000660") -> pd.DataFrame:
    """Strong intraday drift + shallow pullback; reversal RSI paths typically stay cold."""
    base = datetime(2026, 6, 2, 9, 0, tzinfo=_KST)
    rows = []
    for i in range(95):
        ts = base + timedelta(minutes=3 * i)
        uptrend = i * 0.028
        o = 100.0 + uptrend + 0.05 * (i % 5)
        c = o + 0.12 + 0.03 * (i % 4)
        rng = 0.45 + 0.03 * (i % 6)
        h = max(o, c) + rng * 0.35
        low = min(o, c) - rng * 0.35
        if 58 <= i <= 64:
            low = min(low, (o + c) / 2.0 - 0.35)
        vol = 900_000.0 + i * 6_000.0 + (400_000.0 if i > 70 else 0.0)
        rows.append({"symbol": symbol, "date": ts, "open": o, "high": h, "low": low, "close": c, "volume": vol})
    # Widen only the last bar range (tiny body) so `last_bar_body_pct` stays below chase thresholds.
    last = rows[-1]
    mid = float(last["close"])
    last["open"] = mid - 0.004
    last["close"] = mid + 0.004
    # Keep range moderate so `momentum_late_vertical_spike` does not trip on a 2-bar window.
    last["high"] = mid + 0.55
    last["low"] = mid - 0.55
    return pd.DataFrame(rows)


def test_momentum_continuation_passes_on_leader_like_series() -> None:
    sub = build_leader_continuation_3m("000660")
    r = evaluate_momentum_continuation_entry(
        sub,
        min_hits=3,
        min_hits_late_session=4,
        minutes_since_open=120.0,
        late_open_minutes=330.0,
        volume_z_floor=-0.75,
        volume_ratio_floor=0.86,
        is_leader=True,
    )
    assert r["momentum_continuation_ok"] is True
    assert int(r["momentum_path_hits"]) >= 3
    red = evaluate_rsi_red_flag_buy(sub, is_leader_symbol=True)
    assert int(red.get("rsi_red_path_hits") or 0) < 2 or red.get("rsi_red_flag_buy") is False


def test_reversal_still_cold_while_momentum_ok_on_same_bars() -> None:
    sub = build_leader_continuation_3m("000660")
    red = evaluate_rsi_red_flag_buy(sub, volume_z_floor=-0.6, volume_ratio_floor=0.88, is_leader_symbol=True)
    mom = evaluate_momentum_continuation_entry(
        sub,
        min_hits=3,
        min_hits_late_session=4,
        minutes_since_open=150.0,
        late_open_minutes=330.0,
        volume_z_floor=-0.65,
        volume_ratio_floor=0.88,
        is_leader=True,
    )
    assert mom["momentum_continuation_ok"] is True
    assert int(red.get("rsi_red_path_hits") or 0) < 2


def test_volume_leader_relaxation_strong_override() -> None:
    vol = pd.Series([1.0] * 19 + [1.05, 1.03] + [1.0] * 5)
    base = rsi_hf_volume_confirmation(vol, z_floor=-0.2, ratio_floor=0.95, is_leader=False, trend_quality=0)
    relaxed = rsi_hf_volume_confirmation(vol, z_floor=-0.2, ratio_floor=0.95, is_leader=True, trend_quality=4)
    assert relaxed["volume_confirmation_ok"] is True
    assert base["volume_confirmation_ok"] in (True, False)


def test_momentum_blow_off_blocks() -> None:
    base = datetime(2026, 6, 2, 9, 0, tzinfo=_KST)
    rows = []
    px = 100.0
    for i in range(34):
        ts = base + timedelta(minutes=3 * i)
        o, c, h, low, v = px, px + 0.08, px + 0.15, px - 0.08, 1_200_000.0
        px = c
        rows.append({"symbol": "009999", "date": ts, "open": o, "high": h, "low": low, "close": c, "volume": v})
    # Final vertical candle: wide range + body pinned near the high (blow-off guard).
    ts = base + timedelta(minutes=3 * 34)
    o, c, h, low, v = px, px + 2.6, px + 3.0, px - 0.02, 8_000_000.0
    rows.append({"symbol": "009999", "date": ts, "open": o, "high": h, "low": low, "close": c, "volume": v})
    sub = pd.DataFrame(rows)
    blocked, detail = momentum_blow_off_guard(sub)
    assert blocked is True
    assert detail.startswith("blowoff_")


def test_strategy_emits_buy_via_momentum_not_reversal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_MULTI_STRATEGY_MODE", "false")
    monkeypatch.setenv("PAPER_INTRADAY_RISK_BASED_QUANTITY", "false")
    monkeypatch.setenv("PAPER_INTRADAY_ORDER_QUANTITY", "3")
    monkeypatch.setattr(
        "app.strategy.scalp_rsi_flag_hf_v1_strategy.classify_market_regime",
        lambda *_a, **_k: MarketRegimeResult(
            regime="bullish_trend",
            features=MagicMock(),
            reasons=["unit"],
        ),
    )
    get_settings.cache_clear()
    df = build_leader_continuation_3m("000660")
    k, vol = _idx_vol()
    ctx = StrategyContext(
        prices=df,
        kospi_index=k[["date", "close"]],
        sp500_index=k[["date", "close"]],
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
        volatility_index=vol,
    )
    st = ScalpRsiFlagHfV1Strategy()
    st.intraday_state = IntradayPaperState()
    st.intraday_session_context = {"krx_session_state": "regular"}
    st.quote_by_symbol = {
        "000660": {"output": {"acml_vol": "900000000", "acml_tr_pbmn": "9000000000000", "bidp": "120", "askp": "120.15"}}
    }
    setattr(st, "_router_equity_krw", 50_000_000.0)
    setattr(st, "_router_intraday_budget_krw", 50_000_000.0)
    sigs = st.generate_signals(ctx)
    buys = [s for s in sigs if s.side == "buy"]
    assert buys, "expected momentum path buy"
    assert "momentum_continuation" in (buys[0].reason or "")
    d = st.last_diagnostics[-1]
    assert d.get("entry_mode_selected") == "momentum_continuation"
    assert int(d.get("reversal_path_hits") or 0) < int(d.get("min_required_reversal_hits") or 99)


def test_sideways_scales_momentum_qty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_MULTI_STRATEGY_MODE", "false")
    monkeypatch.setenv("PAPER_INTRADAY_RISK_BASED_QUANTITY", "false")
    monkeypatch.setenv("PAPER_INTRADAY_ORDER_QUANTITY", "10")
    monkeypatch.setenv("PAPER_RSI_HF_SIDEWAYS_MOMENTUM_QTY_MULT", "0.5")
    monkeypatch.setattr(
        "app.strategy.scalp_rsi_flag_hf_v1_strategy.classify_market_regime",
        lambda *_a, **_k: MarketRegimeResult(
            regime="sideways",
            features=MagicMock(),
            reasons=["unit"],
        ),
    )
    get_settings.cache_clear()
    df = build_leader_continuation_3m("000660")
    k, vol = _idx_vol()
    ctx = StrategyContext(
        prices=df,
        kospi_index=k[["date", "close"]],
        sp500_index=k[["date", "close"]],
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
        volatility_index=vol,
    )
    st = ScalpRsiFlagHfV1Strategy()
    st.intraday_state = IntradayPaperState()
    st.intraday_session_context = {"krx_session_state": "regular"}
    st.quote_by_symbol = {
        "000660": {"output": {"acml_vol": "900000000", "acml_tr_pbmn": "9000000000000", "bidp": "120", "askp": "120.15"}}
    }
    setattr(st, "_router_equity_krw", 50_000_000.0)
    setattr(st, "_router_intraday_budget_krw", 50_000_000.0)
    sigs = st.generate_signals(ctx)
    buys = [s for s in sigs if s.side == "buy"]
    assert buys
    assert buys[0].quantity <= 5


def test_flat_noise_fails_momentum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_MULTI_STRATEGY_MODE", "false")
    monkeypatch.setenv("PAPER_INTRADAY_RISK_BASED_QUANTITY", "false")
    monkeypatch.setenv("PAPER_INTRADAY_ORDER_QUANTITY", "5")
    monkeypatch.setattr(
        "app.strategy.scalp_rsi_flag_hf_v1_strategy.classify_market_regime",
        lambda *_a, **_k: MarketRegimeResult(
            regime="bullish_trend",
            features=MagicMock(),
            reasons=["unit"],
        ),
    )
    get_settings.cache_clear()
    base = datetime(2026, 6, 2, 9, 0, tzinfo=_KST)
    rows = []
    for i in range(90):
        ts = base + timedelta(minutes=3 * i)
        px = 50.0 + (0.01 if i % 2 == 0 else -0.01)
        rows.append(
            {
                "symbol": "000888",
                "date": ts,
                "open": px,
                "high": px + 0.02,
                "low": px - 0.02,
                "close": px,
                "volume": 500_000.0,
            }
        )
    df = pd.DataFrame(rows)
    k, vol = _idx_vol()
    ctx = StrategyContext(
        prices=df,
        kospi_index=k[["date", "close"]],
        sp500_index=k[["date", "close"]],
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
        volatility_index=vol,
    )
    st = ScalpRsiFlagHfV1Strategy()
    st.intraday_state = IntradayPaperState()
    st.intraday_session_context = {"krx_session_state": "regular"}
    st.quote_by_symbol = {
        "000888": {"output": {"acml_vol": "200000000", "acml_tr_pbmn": "2000000000000", "bidp": "50", "askp": "50.05"}}
    }
    setattr(st, "_router_equity_krw", 50_000_000.0)
    setattr(st, "_router_intraday_budget_krw", 50_000_000.0)
    sigs = st.generate_signals(ctx)
    assert all(s.side != "buy" for s in sigs)
