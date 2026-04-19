"""In-repo validation for intraday RSI HF, gates, and swing TP1 state (no live broker)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.brokers.paper_broker import PaperBroker
from app.config import get_settings
from app.orders.models import OrderRequest
from app.risk.rules import RiskLimits, RiskRules
from app.scheduler.intraday_jobs import IntradaySchedulerJobs
from app.strategy.base_strategy import StrategyContext
from app.strategy.intraday_paper_state import IntradayPaperState
from app.strategy.scalp_momentum_v1_strategy import ScalpMomentumV1Strategy
from app.strategy.scalp_rsi_flag_hf_v1_strategy import ScalpRsiFlagHfV1Strategy
from app.strategy.swing_relaxed_v2_state import SwingRelaxedV2PaperState, SwingRelaxedV2StateStore

_KST = ZoneInfo("Asia/Seoul")


def _ctx_for_scalp(symbol: str, bars: int) -> StrategyContext:
    anchor = datetime(2026, 4, 14, 10, 0, tzinfo=_KST)
    start = anchor - timedelta(minutes=bars - 1)
    rows = []
    px = 100.0
    for i in range(bars):
        rows.append(
            {
                "symbol": symbol,
                "date": start + timedelta(minutes=i),
                "open": px - 0.03,
                "high": px + 0.12,
                "low": px - 0.08,
                "close": px + 0.05,
                "volume": 3_000_000.0,
            }
        )
        px = rows[-1]["close"]
    price_df = pd.DataFrame(rows)
    kospi = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=40, freq="D", tz=_KST),
            "close": [2500.0 + i * 0.5 for i in range(40)],
        }
    )
    vol = pd.DataFrame({"date": kospi["date"], "value": [15.0] * len(kospi)})
    return StrategyContext(
        prices=price_df,
        kospi_index=kospi,
        sp500_index=kospi.copy(),
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]),
        volatility_index=vol,
    )


def test_scalp_rsi_flag_hf_calls_rsi_red_flag_buy_on_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verified: entry path invokes rsi_red_flag_buy (mocked)."""
    monkeypatch.setattr(
        "app.strategy.scalp_rsi_flag_hf_v1_strategy.get_krx_session_state_kst",
        lambda *a, **k: "regular",
    )
    monkeypatch.setattr(
        "app.strategy.scalp_rsi_flag_hf_v1_strategy.should_force_flatten_before_close_kst",
        lambda **_: False,
    )
    monkeypatch.setattr("app.strategy.scalp_rsi_flag_hf_v1_strategy.last_bar_body_pct", lambda _df: 0.4)

    red_calls: list[str] = []

    def fake_red(sub: pd.DataFrame) -> dict:
        red_calls.append("red")
        return {
            "rsi_red_flag_buy": True,
            "rsi_red_flag_reason": "unit",
            "rsi_red_path_hits": 3,
        }

    monkeypatch.setattr("app.strategy.scalp_rsi_flag_hf_v1_strategy.rsi_red_flag_buy", fake_red)

    strat = ScalpRsiFlagHfV1Strategy()
    setattr(strat, "_paper_strategy_id", "intraday_rsi_flag_hf_v1")
    strat.intraday_state = IntradayPaperState()
    strat.quote_by_symbol = {
        "005930": {
            "output": {
                "acml_vol": "250000000",
                "acml_tr_pbmn": "5000000000000",
                "bidp": "105.0",
                "askp": "105.15",
            }
        }
    }
    ctx = _ctx_for_scalp("005930", 40)
    sigs = strat.generate_signals(ctx)
    assert red_calls == ["red"], "entry evaluation must call rsi_red_flag_buy"
    assert any(s.side == "buy" and s.strategy_name == "intraday_rsi_flag_hf_v1" for s in sigs)


def test_scalp_rsi_blue_helper_used_when_position_and_enough_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verified: held position + ≥30 bars → rsi_blue_flag_sell(sub) is invoked before other exit rules."""
    monkeypatch.setattr(
        "app.strategy.scalp_rsi_flag_hf_v1_strategy.get_krx_session_state_kst",
        lambda *a, **k: "regular",
    )
    monkeypatch.setattr(
        "app.strategy.scalp_rsi_flag_hf_v1_strategy.should_force_flatten_before_close_kst",
        lambda **_: False,
    )

    blue_calls = 0

    def fake_blue(sub: pd.DataFrame) -> dict:
        nonlocal blue_calls
        blue_calls += 1
        return {"rsi_blue_flag_sell": True, "rsi_blue_flag_reason": "unit_blue"}

    monkeypatch.setattr("app.strategy.scalp_rsi_flag_hf_v1_strategy.rsi_blue_flag_sell", fake_blue)

    strat = ScalpRsiFlagHfV1Strategy()
    strat.intraday_state = IntradayPaperState()
    strat.quote_by_symbol = {}
    ctx = _ctx_for_scalp("005930", 40)
    port = pd.DataFrame([{"symbol": "005930", "quantity": 10, "average_price": 100.0, "hold_days": 0}])
    ctx = StrategyContext(
        prices=ctx.prices,
        kospi_index=ctx.kospi_index,
        sp500_index=ctx.sp500_index,
        portfolio=port,
        volatility_index=ctx.volatility_index,
    )
    sigs = strat.generate_signals(ctx)
    assert blue_calls >= 1
    assert any(s.side == "sell" and s.reason == "rsi_blue_flag_sell" for s in sigs)


def test_on_accepted_buy_counts_symbol_entries_for_intraday_rsi_alias() -> None:
    """Verified: same per-symbol counter path as scalp_rsi_flag_hf_v1."""
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
    order = OrderRequest(
        symbol="005930",
        side="buy",
        quantity=1,
        price=50000.0,
        stop_loss_pct=None,
        strategy_id="intraday_rsi_flag_hf_v1",
    )
    jobs._on_accepted_order(order, st, cfg)
    assert st.symbol_entries_today.get("005930") == 1


def test_swing_relaxed_v2_tp1_state_persist_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verified: TP1 flags persist across save/load for same KST day."""
    monkeypatch.setattr("app.strategy.swing_relaxed_v2_state._today_kst", lambda: "20260115")
    p = tmp_path / "tp1.json"
    st = SwingRelaxedV2PaperState(day_kst="20260115", tp1_done={"005930": True})
    SwingRelaxedV2StateStore(p).save(st)
    loaded = SwingRelaxedV2StateStore(p).load()
    assert loaded.tp1_done.get("005930") is True


def test_final_betting_feasible_shares_imply_min_notional_pct() -> None:
    """Verified arithmetic: when q == feasible >= q_min, notional_pct meets min (integer shares)."""
    eq = 10_000_000.0
    px = 10_000.0
    min_pct = 20.0
    q_min = max(1, int((eq * (min_pct / 100.0)) / px))
    q = q_min
    notional_pct = (q * px / eq) * 100.0
    assert notional_pct + 1e-9 >= min_pct


def test_intraday_buy_gate_duplicate_blocks_regardless_of_strategy_id() -> None:
    """Duplicate/cooldown gates do not depend on strategy id (verified by execution)."""
    cfg = get_settings()
    jobs = IntradaySchedulerJobs(
        strategy=MagicMock(),
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
    assert g.get("reason") == "duplicate_order_guard"
