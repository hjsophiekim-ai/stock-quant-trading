"""
Enhanced tests for final_betting_v1 strategy improvements:
- Early entry window (14:30 start)
- Aggressive mode relaxations
- Enhanced diagnostics
- Market filter relaxations in aggressive mode
"""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.config import get_settings
from app.strategy.base_strategy import StrategyContext
from app.strategy.final_betting_v1_strategy import (
    FinalBettingV1Strategy,
    set_final_betting_debug_now,
)
from app.strategy.intraday_paper_state import IntradayPaperState
from app.strategy.market_mode_policy import compose_effective_policy

_KST = ZoneInfo("Asia/Seoul")


def _index_frame(n: int = 130) -> pd.DataFrame:
    """Create index frame with positive trend to pass market filters."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=n, freq="D", tz=_KST),
            "close": [100.0 * (1.01**i) for i in range(n)],
            "value": [15.0 + 0.01 * i for i in range(n)],
        }
    )


def _minute_series(symbol: str, ymd: str, trend: str = "up") -> pd.DataFrame:
    """Create minute bars with specified trend."""
    day = datetime.strptime(ymd, "%Y%m%d").replace(tzinfo=_KST)
    rows = []
    px = 100.0
    
    for i in range(380):
        ts = day.replace(hour=9, minute=0) + pd.Timedelta(minutes=i)
        if ts.hour == 15 and ts.minute > 20:
            break
            
        if trend == "up":
            o, h, low, c = px, px + 0.15, px - 0.05, px + 0.08
        elif trend == "rebound":
            # Create bearish rebound pattern
            if i < 200:  # First half: decline
                c = px - 0.05
                h = px + 0.02
                low = px - 0.08
            else:  # Second half: recovery
                c = px + 0.12
                h = px + 0.18
                low = px - 0.02
            o = px
        else:
            o, h, low, c = px, px + 0.05, px - 0.15, px - 0.08
            
        rows.append(
            {
                "symbol": symbol,
                "date": ts,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 15_000.0,
            }
        )
        px = c
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def _clear_fb_debug():
    yield
    set_final_betting_debug_now(None)
    get_settings.cache_clear()


class TestEnhancedEntryWindow:
    """Test enhanced entry window functionality."""

    def test_entry_window_starts_at_1430(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that entry evaluation begins at 14:30 KST."""
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
        
        strat.generate_signals(ctx)
        breakdown = strat.last_intraday_signal_breakdown
        
        assert breakdown["entry_window_open"] is True
        assert breakdown["entry_window_label"] == "early_close_betting"
        assert breakdown["current_kst_hhmm"] == "1430"
        assert breakdown["early_close_betting_window"] is True
        assert breakdown["core_close_betting_window"] is False

    def test_entry_window_before_1430_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that entry evaluation is blocked before 14:30."""
        monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
        get_settings.cache_clear()
        
        strat = FinalBettingV1Strategy()
        set_final_betting_debug_now(datetime(2026, 4, 16, 14, 29, tzinfo=_KST))
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
        breakdown = strat.last_intraday_signal_breakdown
        
        assert breakdown["entry_window_open"] is False
        assert breakdown["entry_window_label"] == "closed"
        assert breakdown["current_kst_hhmm"] == "1429"
        assert breakdown["early_close_betting_window"] is False

    def test_core_close_betting_window_1500_1518(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test core close-betting window 15:00-15:18."""
        monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
        get_settings.cache_clear()
        
        strat = FinalBettingV1Strategy()
        set_final_betting_debug_now(datetime(2026, 4, 16, 15, 10, tzinfo=_KST))
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
        breakdown = strat.last_intraday_signal_breakdown
        
        assert breakdown["entry_window_open"] is True
        assert breakdown["entry_window_label"] == "core_close_betting"
        assert breakdown["current_kst_hhmm"] == "1510"
        assert breakdown["core_close_betting_window"] is True

    def test_final_auction_window_after_1518(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test final auction window after 15:18."""
        monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
        get_settings.cache_clear()
        
        strat = FinalBettingV1Strategy()
        set_final_betting_debug_now(datetime(2026, 4, 16, 15, 19, tzinfo=_KST))
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
        breakdown = strat.last_intraday_signal_breakdown
        
        assert breakdown["entry_window_open"] is False
        assert breakdown["entry_window_label"] == "final_auction_closed"
        assert breakdown["final_auction_window"] is True


class TestAggressiveModeRelaxations:
    """Test aggressive mode relaxations."""

    def test_aggressive_mode_more_permissive_than_neutral(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that aggressive mode allows entries where neutral blocks."""
        monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
        get_settings.cache_clear()
        
        # Test aggressive mode
        strat_aggressive = FinalBettingV1Strategy()
        strat_aggressive._paper_market_mode_snapshot = {
            "market_mode_active": "aggressive",
            "policy": compose_effective_policy(active_mode="aggressive", cfg=get_settings())["final_betting"]
        }
        set_final_betting_debug_now(datetime(2026, 4, 16, 15, 10, tzinfo=_KST))
        strat_aggressive.intraday_state = IntradayPaperState(day_kst="20260416")
        strat_aggressive.intraday_session_context = {"krx_session_state": "regular"}
        
        # Test neutral mode
        strat_neutral = FinalBettingV1Strategy()
        strat_neutral._paper_market_mode_snapshot = {
            "market_mode_active": "neutral",
            "policy": compose_effective_policy(active_mode="neutral", cfg=get_settings())["final_betting"]
        }
        strat_neutral.intraday_state = IntradayPaperState(day_kst="20260416")
        strat_neutral.intraday_session_context = {"krx_session_state": "regular"}
        
        # Create borderline candidate data
        df = _minute_series("005930", "20260416", "rebound")
        idx = _index_frame()
        ctx = StrategyContext(
            prices=df,
            kospi_index=idx[["date", "close"]].copy(),
            sp500_index=idx[["date", "close"]].copy(),
            portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
            volatility_index=idx[["date", "value"]].copy(),
        )
        
        # Test aggressive mode
        strat_aggressive.generate_signals(ctx)
        aggressive_breakdown = strat_aggressive.last_intraday_signal_breakdown
        
        # Test neutral mode  
        strat_neutral.generate_signals(ctx)
        neutral_breakdown = strat_neutral.last_intraday_signal_breakdown
        
        # Aggressive should have more permissive hit thresholds
        assert aggressive_breakdown["fb_hit_thresholds"]["effective_min_hits"] <= neutral_breakdown["fb_hit_thresholds"]["effective_min_hits"]
        assert aggressive_breakdown["fb_hit_thresholds"]["aggressive_entry_relaxation_applied"] is True
        assert neutral_breakdown["fb_hit_thresholds"]["aggressive_entry_relaxation_applied"] is False

    def test_market_filter_relaxation_in_aggressive_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test market filter relaxation in aggressive mode for borderline conditions."""
        monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
        get_settings.cache_clear()
        
        strat = FinalBettingV1Strategy()
        strat._paper_market_mode_snapshot = {
            "market_mode_active": "aggressive",
            "policy": compose_effective_policy(active_mode="aggressive", cfg=get_settings())["final_betting"]
        }
        set_final_betting_debug_now(datetime(2026, 4, 16, 15, 10, tzinfo=_KST))
        strat.intraday_state = IntradayPaperState(day_kst="20260416")
        strat.intraday_session_context = {"krx_session_state": "regular"}
        
        # Create borderline market conditions (slightly below hard thresholds)
        idx = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=130, freq="D", tz=_KST),
                "close": [100.0 * (0.998**i) for i in range(130)],  # Slight decline
                "value": [15.0 + 0.01 * i for i in range(130)],
            }
        )
        
        df = _minute_series("005930", "20260416")
        ctx = StrategyContext(
            prices=df,
            kospi_index=idx[["date", "close"]].copy(),
            sp500_index=idx[["date", "close"]].copy(),
            portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
            volatility_index=idx[["date", "value"]].copy(),
        )
        
        strat.generate_signals(ctx)
        breakdown = strat.last_intraday_signal_breakdown
        
        # Should show market filter enhancement diagnostics
        assert "market_filter_ok_effective_enhanced" in breakdown
        assert "market_filter_penalty_applied" in breakdown
        assert "reduced_size_due_to_market_filter" in breakdown
        assert "aggressive_entry_relaxation_applied" in breakdown

    def test_rebound_core_weighting_in_aggressive_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test enhanced rebound core weighting in aggressive mode."""
        monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
        get_settings.cache_clear()
        
        strat = FinalBettingV1Strategy()
        strat._paper_market_mode_snapshot = {
            "market_mode_active": "aggressive",
            "policy": compose_effective_policy(active_mode="aggressive", cfg=get_settings())["final_betting"]
        }
        set_final_betting_debug_now(datetime(2026, 4, 16, 15, 10, tzinfo=_KST))
        strat.intraday_state = IntradayPaperState(day_kst="20260416")
        strat.intraday_session_context = {"krx_session_state": "regular"}
        
        df = _minute_series("005930", "20260416", "rebound")
        idx = _index_frame()
        ctx = StrategyContext(
            prices=df,
            kospi_index=idx[["date", "close"]].copy(),
            sp500_index=idx[["date", "close"]].copy(),
            portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
            volatility_index=idx[["date", "value"]].copy(),
        )
        
        strat.generate_signals(ctx)
        breakdown = strat.last_intraday_signal_breakdown
        
        # Should show rebound core activity
        assert "rebound_core_active" in breakdown["fb_hit_thresholds"]
        assert "late_recovery_path_active" in breakdown["fb_hit_thresholds"]


class TestEnhancedDiagnostics:
    """Test enhanced diagnostics fields."""

    def test_comprehensive_diagnostics_populated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that all new diagnostic fields are populated."""
        monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
        get_settings.cache_clear()
        
        strat = FinalBettingV1Strategy()
        strat._paper_market_mode_snapshot = {
            "market_mode_active": "aggressive",
            "policy": compose_effective_policy(active_mode="aggressive", cfg=get_settings())["final_betting"]
        }
        set_final_betting_debug_now(datetime(2026, 4, 16, 14, 45, tzinfo=_KST))
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
        breakdown = strat.last_intraday_signal_breakdown
        
        # Check entry window diagnostics
        required_entry_fields = [
            "entry_window_open",
            "entry_window_label", 
            "current_kst_hhmm",
            "early_close_betting_window",
            "core_close_betting_window",
            "final_auction_window"
        ]
        
        for field in required_entry_fields:
            assert field in breakdown, f"Missing diagnostic field: {field}"
        
        # Check market filter diagnostics
        required_market_fields = [
            "market_filter_ok_effective_enhanced",
            "market_filter_penalty_applied",
            "reduced_size_due_to_market_filter",
            "aggressive_entry_relaxation_applied"
        ]
        
        for field in required_market_fields:
            assert field in breakdown, f"Missing market filter diagnostic: {field}"
        
        # Check final betting diagnostics (only set when entries are evaluated)
        if breakdown.get("entries_evaluated", 0) > 0:
            required_final_fields = [
                "final_betting_position_alloc_pct",
                "final_betting_entry_block_reason"
            ]
            
            for field in required_final_fields:
                assert field in breakdown, f"Missing final betting diagnostic: {field}"


class TestMarketModePolicyEnhancements:
    """Test enhanced market mode policy settings."""

    def test_aggressive_mode_substantially_more_permissive(self) -> None:
        """Test that aggressive mode settings are substantially more permissive."""
        cfg = get_settings()
        aggressive_policy = compose_effective_policy(active_mode="aggressive", cfg=cfg)["final_betting"]
        neutral_policy = compose_effective_policy(active_mode="neutral", cfg=cfg)["final_betting"]
        
        # Check that aggressive mode is meaningfully more permissive
        assert aggressive_policy["us_night_hard_delta"] < neutral_policy["us_night_hard_delta"]
        assert aggressive_policy["kospi_hard_delta"] < neutral_policy["kospi_hard_delta"] 
        assert aggressive_policy["rank_pool_delta"] > neutral_policy["rank_pool_delta"]
        assert aggressive_policy["max_new_positions_delta"] > neutral_policy["max_new_positions_delta"]
        assert aggressive_policy["rebound_score_delta"] < neutral_policy["rebound_score_delta"]
        assert aggressive_policy["min_trade_value_mult"] < neutral_policy["min_trade_value_mult"]
        assert aggressive_policy["size_mult"] > neutral_policy["size_mult"]
        
        # Check specific enhanced values
        assert aggressive_policy["us_night_hard_delta"] <= -0.58  # Much softer
        assert aggressive_policy["kospi_hard_delta"] <= -0.65   # Much softer
        assert aggressive_policy["rank_pool_delta"] >= 6         # Larger pool
        assert aggressive_policy["max_new_positions_delta"] >= 3   # More positions
        assert aggressive_policy["rebound_score_delta"] <= -0.22   # Easier rebound
        assert aggressive_policy["min_trade_value_mult"] <= 0.82   # Lower threshold
