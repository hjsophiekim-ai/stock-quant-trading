"""백엔드 signal_engine 단위 테스트."""

from __future__ import annotations

import pandas as pd
from zoneinfo import ZoneInfo

from app.orders.models import OrderSignal
from backend.app.strategy.signal_engine import (
    DuplicateSignalSuppressor,
    SwingSignalEngine,
    merge_daily_with_live,
)
from backend.app.strategy.signal_models import LiveQuoteView, StandardEngineSignal, SwingSignalEngineConfig

_KST = ZoneInfo("Asia/Seoul")


def _ohlc_series(symbol: str, closes: list[float]) -> pd.DataFrame:
    rows = []
    for i, c in enumerate(closes):
        o = c * 0.998
        h = c * 1.01
        low = c * 0.99
        d = pd.Timestamp(2025, 1, 1, tz=_KST) + pd.Timedelta(days=i)
        rows.append({"symbol": symbol, "date": d, "open": o, "high": h, "low": low, "close": c, "volume": 1_000_000.0})
    return pd.DataFrame(rows)


def test_merge_daily_with_live_updates_close() -> None:
    df = _ohlc_series("TST", [100.0, 101.0, 102.0])
    live = LiveQuoteView(symbol="TST", last=105.0, open=100.0, high=106.0, low=99.0)
    out = merge_daily_with_live(df, live)
    assert float(out.iloc[-1]["close"]) == 105.0


def test_standard_engine_signal_to_order_signal() -> None:
    s = StandardEngineSignal(
        symbol="005930",
        side="buy",
        quantity=5,
        limit_price=70000.0,
        stop_loss_pct=4.0,
        strategy_id="swing_signal_engine",
        kind="entry_leg1",
        reasons=["test"],
        signal_id="fixed-id",
    )
    os = s.to_order_signal()
    assert isinstance(os, OrderSignal)
    assert os.symbol == "005930"
    assert os.signal_id == "fixed-id"


def test_duplicate_suppressor_ttl() -> None:
    d = DuplicateSignalSuppressor(ttl_sec=60.0)
    assert d.should_emit("A", "entry_leg1") is True
    assert d.should_emit("A", "entry_leg1") is False
    assert d.should_emit("A", "entry_leg2") is True


def test_swing_engine_skips_without_quote() -> None:
    eng = SwingSignalEngine(cfg=SwingSignalEngineConfig(order_quantity=10), suppress_ttl_sec=1.0)
    df = _ohlc_series("X", [float(100 + i * 0.1) for i in range(80)])
    snap = eng.evaluate(df, {}, pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]))
    assert snap.signals == []
    assert any("실시간 호가 없음" in (d.narrative[0] if d.narrative else "") for d in snap.per_symbol)


def test_evaluate_emits_exit_stop_when_position_loss() -> None:
    """보유 + 실시간 호가 + 손절 구간이면 매도 신호."""
    eng = SwingSignalEngine(cfg=SwingSignalEngineConfig(order_quantity=10), suppress_ttl_sec=0.1)
    closes = [50.0 + i * 0.8 for i in range(80)]
    closes[-1] = 100.0
    df = _ohlc_series("Z", closes)
    port = pd.DataFrame([{"symbol": "Z", "quantity": 10, "average_price": 120.0, "hold_days": 1}])
    live = LiveQuoteView(symbol="Z", last=100.0, open=99.0, high=101.0, low=98.0)
    snap = eng.evaluate(df, {"Z": live}, port, market_regime="bullish_trend")
    kinds = [s.kind for s in snap.signals]
    assert "exit_stop_loss" in kinds
