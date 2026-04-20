"""End-to-end style integration tests for final_betting_v1 (no live KIS)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.orders.models import OrderRequest, OrderResult
from app.strategy.base_strategy import StrategyContext
from app.strategy.final_betting_v1_strategy import FinalBettingV1Strategy, set_final_betting_debug_now
from app.strategy.intraday_paper_state import IntradayPaperState
from app.strategy.regime_soft import SoftRegimeResult, compute_soft_regime

_KST = ZoneInfo("Asia/Seoul")


def _index_frame(n: int = 130) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=n, freq="D", tz=_KST),
            "close": [100.0 * (1.01**i) for i in range(n)],
            "value": [15.0 + 0.01 * i for i in range(n)],
        }
    )


def _minute_series_organic_bearish_rebound(symbol: str, ymd: str) -> pd.DataFrame:
    """OHLC where real evaluate_bearish_rebound_candidate passes (bearish day + late uptrend)."""
    day = datetime.strptime(ymd, "%Y%m%d").replace(tzinfo=_KST)
    rows = []
    for i in range(380):
        ts = day.replace(hour=9, minute=0) + pd.Timedelta(minutes=i)
        if ts.hour == 15 and ts.minute > 20:
            break
        if i < 120:
            o = 100.0 + i * 0.002
            c = o + 0.03
            h, low = max(o, c) + 0.15, min(o, c) - 0.1
        elif i < 280:
            o = 100.2 - (i - 120) * 0.008
            c = o - 0.02
            h, low = max(o, c) + 0.2, min(o, c) - 0.15
        else:
            j = i - 280
            o = 98.2 + j * 0.012
            c = o + 0.02
            h, low = max(o, c) + 0.06, min(o, c) - 0.04
        rows.append(
            {
                "symbol": symbol,
                "date": ts,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 80000.0,
            }
        )
    return pd.DataFrame(rows)


def _minute_series(symbol: str, ymd: str) -> pd.DataFrame:
    day = datetime.strptime(ymd, "%Y%m%d").replace(tzinfo=_KST)
    rows = []
    px = 50000.0
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
                "volume": 50_000.0,
            }
        )
        px = c
    return pd.DataFrame(rows)


def _kis_quote_liquidity_ok() -> dict:
    return {
        "output": {
            "acml_tr_pbmn": 12_000_000_000.0,
            "bidp": 50000.0,
            "askp": 50100.0,
            "frgn_ntby_rank": 5,
            "orgn_ntby_rank": 8,
            "market_cap": 80_000_000_000.0,
            "frgn_ntby_amt": 5_000_000_000.0,
            "orgn_ntby_amt": 3_000_000_000.0,
        }
    }


@pytest.fixture(autouse=True)
def _clear():
    yield
    set_final_betting_debug_now(None)
    get_settings.cache_clear()


def test_soft_regime_gate_blocks_entries_when_entry_not_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()

    def _blocked(feat, leg):
        return SoftRegimeResult(
            market_regime="bearish",
            regime_score=-0.8,
            regime_entry_allowed=False,
            regime_size_multiplier=0.3,
            regime_block_reason="high_volatility_risk",
        )

    monkeypatch.setattr(
        "app.strategy.final_betting_v1_strategy.compute_soft_regime",
        _blocked,
    )
    strat = FinalBettingV1Strategy()
    set_final_betting_debug_now(datetime(2026, 4, 16, 15, 12, tzinfo=_KST))
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
    assert strat.last_intraday_signal_breakdown.get("soft_regime_used_as_gate") is True
    assert strat.last_intraday_signal_breakdown.get("regime_gate_decision") == "blocked"
    assert strat.last_intraday_signal_breakdown.get("blocked") == "soft_regime_entry_not_allowed"
    assert all(s.side != "buy" for s in sigs)


def test_soft_regime_gate_allowed_path_uses_live_compute_outside_entry_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Soft gate runs before entry window; allowed + real compute_soft_regime without mocks."""
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()

    strat = FinalBettingV1Strategy()
    set_final_betting_debug_now(datetime(2026, 4, 16, 14, 30, tzinfo=_KST))
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
    assert strat.last_intraday_signal_breakdown.get("soft_regime_used_as_gate") is True
    assert strat.last_intraday_signal_breakdown.get("regime_gate_decision") == "allowed"
    assert strat.last_intraday_signal_breakdown.get("blocked") != "soft_regime_entry_not_allowed"
    assert strat.last_intraday_signal_breakdown.get("entry_window") == "closed"
    assert all(s.side != "buy" for s in sigs)


def test_rebound_organic_emit_buy_without_evaluate_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real evaluate_bearish_rebound_candidate + sizing path emits buy (no rebound monkeypatch)."""
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    monkeypatch.setenv("PAPER_FINAL_BETTING_REBOUND_SCORE_MIN", "0.45")
    get_settings.cache_clear()

    strat = FinalBettingV1Strategy()
    setattr(strat, "_final_betting_equity_krw", 80_000_000.0)
    strat.quote_by_symbol = {
        "005930": {
            "output": {"acml_tr_pbmn": 12_000_000_000.0},
            "bidp": 99.45,
            "askp": 99.55,
            "frgn_ntby_rank": 5,
            "orgn_ntby_rank": 8,
            "market_cap": 80_000_000_000.0,
            "frgn_ntby_amt": 5_000_000_000.0,
            "orgn_ntby_amt": 3_000_000_000.0,
        }
    }
    set_final_betting_debug_now(datetime(2026, 4, 16, 15, 12, tzinfo=_KST))
    strat.intraday_state = IntradayPaperState(day_kst="20260416")
    strat.intraday_session_context = {"krx_session_state": "regular"}
    df = _minute_series_organic_bearish_rebound("005930", "20260416")
    idx = _index_frame()
    ctx = StrategyContext(
        prices=df,
        kospi_index=idx[["date", "close"]].copy(),
        sp500_index=idx[["date", "close"]].copy(),
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
        volatility_index=idx[["date", "value"]].copy(),
    )
    sigs = strat.generate_signals(ctx)
    buys = [s for s in sigs if s.side == "buy"]
    assert buys and buys[0].symbol == "005930"
    entered = [d for d in strat.last_diagnostics if d.get("entered") is True]
    assert entered
    assert entered[0].get("bearish_rebound_candidate") is True
    assert entered[0].get("final_betting_entry_aggressive") is True
    pct = float(entered[0].get("final_betting_position_alloc_pct") or 0.0)
    assert pct >= 19.9


def test_rebound_path_emits_buy_with_rebound_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bearish-close rebound detector stub + 실분봉·호가로 generate_signals 가 매수 1건 생성."""
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    monkeypatch.setenv("PAPER_FINAL_BETTING_REBOUND_SCORE_MIN", "0.45")
    get_settings.cache_clear()

    def _fake_rebound(**_kwargs):
        return {
            "bearish_rebound_candidate": True,
            "final_betting_bearish_close_pattern": "pattern_A",
            "final_betting_reversal_score": 0.65,
            "final_betting_quality_score": 0.55,
            "final_betting_score": 0.58,
            "final_betting_rebound_block_reason": None,
            "final_betting_block_reason": None,
            "panic_candle": False,
            "pattern_scores": {"A": 0.5, "B": 0.0, "C": 0.0},
        }

    monkeypatch.setattr(
        "app.strategy.final_betting_v1_strategy.evaluate_bearish_rebound_candidate",
        _fake_rebound,
    )
    strat = FinalBettingV1Strategy()
    setattr(strat, "_final_betting_equity_krw", 80_000_000.0)
    strat.quote_by_symbol = {"005930": _kis_quote_liquidity_ok()}
    set_final_betting_debug_now(datetime(2026, 4, 16, 15, 12, tzinfo=_KST))
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
    buys = [s for s in sigs if s.side == "buy"]
    assert buys, "expected a buy signal on rebound-stub path"
    assert buys[0].symbol == "005930"
    entered = [d for d in strat.last_diagnostics if d.get("entered") is True]
    assert entered
    assert entered[0].get("final_betting_entry_aggressive") is True
    assert entered[0].get("bearish_rebound_candidate") is True


def test_min_allocation_passes_when_feasible_meets_q_min(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    monkeypatch.setenv("PAPER_FINAL_BETTING_REBOUND_SCORE_MIN", "0.45")
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.strategy.final_betting_v1_strategy.evaluate_bearish_rebound_candidate",
        lambda **_kw: {
            "bearish_rebound_candidate": True,
            "final_betting_quality_score": 0.55,
            "final_betting_reversal_score": 0.65,
            "panic_candle": False,
            "final_betting_bearish_close_pattern": "pattern_A",
            "final_betting_rebound_block_reason": None,
            "final_betting_block_reason": None,
            "final_betting_score": 0.55,
            "pattern_scores": {},
        },
    )
    strat = FinalBettingV1Strategy()
    setattr(strat, "_final_betting_equity_krw", 80_000_000.0)
    strat.quote_by_symbol = {"005930": _kis_quote_liquidity_ok()}
    set_final_betting_debug_now(datetime(2026, 4, 16, 15, 12, tzinfo=_KST))
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
    strat.generate_signals(ctx)
    ent = [d for d in strat.last_diagnostics if d.get("entered") is True]
    assert ent
    pct = float(ent[0].get("final_betting_position_alloc_pct") or 0.0)
    assert pct >= 19.9, f"allocation {pct} should meet ~20% min"


def test_min_allocation_skips_when_feasible_below_q_min(monkeypatch: pytest.MonkeyPatch) -> None:
    """리스크 역산 수량이 최소 배분 주수보다 작을 때 실제 sizing 경로에서 스킵."""
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    monkeypatch.setenv("PAPER_FINAL_BETTING_REBOUND_SCORE_MIN", "0.45")
    monkeypatch.setenv("PAPER_RISK_PER_TRADE_PCT", "0.01")
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.strategy.final_betting_v1_strategy.evaluate_bearish_rebound_candidate",
        lambda **_kw: {
            "bearish_rebound_candidate": True,
            "final_betting_quality_score": 0.55,
            "final_betting_reversal_score": 0.65,
            "panic_candle": False,
            "final_betting_bearish_close_pattern": "pattern_A",
            "final_betting_rebound_block_reason": None,
            "final_betting_block_reason": None,
            "final_betting_score": 0.55,
            "pattern_scores": {},
        },
    )
    strat = FinalBettingV1Strategy()
    setattr(strat, "_final_betting_equity_krw", 5_000_000.0)
    strat.quote_by_symbol = {"005930": _kis_quote_liquidity_ok()}
    set_final_betting_debug_now(datetime(2026, 4, 16, 15, 12, tzinfo=_KST))
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
    strat.generate_signals(ctx)
    blocked = [d for d in strat.last_diagnostics if d.get("blocked_reason") == "insufficient_budget_for_min_allocation"]
    assert blocked, strat.last_diagnostics
    assert blocked[0].get("final_betting_feasible_shares", 0) < blocked[0].get("final_betting_q_min_for_min_alloc", 999)


def test_ledger_prefers_broker_avg_fill_over_order_price(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.brokers.paper_broker import PaperBroker

    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    broker = PaperBroker(initial_cash=50_000_000.0)
    buy = OrderRequest(
        symbol="005930",
        side="buy",
        quantity=100,
        price=50_000.0,
        strategy_id="final_betting_v1",
    )
    br = broker.place_order(buy)
    assert br.accepted and br.avg_fill_price == 50_000.0
    strat = FinalBettingV1Strategy()
    st = IntradayPaperState(day_kst="20260420")
    st.final_betting_carry = {"positions": {"005930": {"shares": 100, "ref_close": 48_000.0}}}
    sell = OrderRequest(
        symbol="005930",
        side="sell",
        quantity=100,
        price=49_000.0,
        signal_reason="gap_up_take_profit",
        strategy_id="final_betting_v1",
    )
    sr = broker.place_order(sell)
    assert sr.avg_fill_price == 49_000.0
    strat.on_fb_sell_accepted("005930", 100, st, order=sell, fill_result=sr)
    row = st.final_betting_carry["fb_perf_ledger"][-1]
    assert row["pnl_price_source"] == "broker_avg_fill"
    assert row["executed_avg_fill_price"] == 49_000.0
    assert row["order_request_price"] == 49_000.0
    expected_pnl = (49_000.0 - 48_000.0) * 100
    assert row["pnl_krw"] == pytest.approx(expected_pnl, rel=1e-6)


def test_ledger_fallback_when_no_fill_result_uses_order_price() -> None:
    strat = FinalBettingV1Strategy()
    st = IntradayPaperState(day_kst="20260420")
    st.final_betting_carry = {"positions": {"005930": {"shares": 10, "ref_close": 100.0}}}
    order = OrderRequest(
        symbol="005930",
        side="sell",
        quantity=10,
        price=105.0,
        signal_reason="x",
        strategy_id="final_betting_v1",
    )
    strat.on_fb_sell_accepted("005930", 10, st, order=order, fill_result=None)
    row = st.final_betting_carry["fb_perf_ledger"][-1]
    assert row["pnl_price_source"] == "order_request_price"
    assert row["fill_px"] == 105.0


def test_paper_intraday_accept_chain_with_fill_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """FinalBettingIntradayJobs 가 브로커 체결가(fill_result)를 on_fb_sell_accepted 로 전달."""
    from app.scheduler.final_betting_intraday_jobs import FinalBettingIntradayJobs
    from app.orders.models import OrderStatus
    from app.risk.rules import RiskLimits, RiskRules

    lim = RiskLimits(
        min_position_weight=0.001,
        max_position_weight=0.99,
        max_positions=20,
        daily_loss_limit_pct=99.0,
        total_loss_limit_pct=99.0,
        default_stop_loss_pct=99.0,
    )
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    get_settings.cache_clear()
    strat = FinalBettingV1Strategy()
    st = IntradayPaperState(day_kst="20260420")
    st.final_betting_carry = {"positions": {"005930": {"shares": 5, "ref_close": 50_000.0}}}
    jobs = FinalBettingIntradayJobs(
        strategy=strat,
        broker=MagicMock(),
        risk_rules=RiskRules(lim),
        kill_switch=None,
        equity_tracker=None,
        state_store=None,
    )
    cfg = get_settings()
    order = OrderRequest(
        symbol="005930",
        side="sell",
        quantity=5,
        price=51_000.0,
        signal_reason="test_exit",
        strategy_id="final_betting_v1",
    )
    fill = OrderResult(
        order_id="sim-1",
        accepted=True,
        message="filled",
        status=OrderStatus.FILLED,
        filled_quantity=5,
        avg_fill_price=51_250.0,
    )
    jobs._on_accepted_order(order, st, cfg, fill_result=fill)
    assert st.final_betting_carry.get("fb_perf_ledger")
    row = st.final_betting_carry["fb_perf_ledger"][-1]
    assert row["pnl_price_source"] == "broker_avg_fill"
    assert row["fill_px"] == 51_250.0


def test_compute_soft_regime_real_call_still_allowed_for_default_index() -> None:
    from app.strategy.market_regime import MarketRegimeFeatures

    feats = MarketRegimeFeatures(
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
    r = compute_soft_regime(feats, "sideways")
    assert r.regime_entry_allowed is True
    assert r.market_regime == "mild_bullish"
