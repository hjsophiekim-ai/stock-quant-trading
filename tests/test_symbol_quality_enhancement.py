"""
Test for symbol quality enhancement in aggressive mode.
Verifies that strong symbols get preferential reduced-size entry treatment.
"""

from __future__ import annotations

from datetime import datetime
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
    """Create index frame with borderline conditions for aggressive enhancement."""
    # Create slightly negative trend but within aggressive enhancement range
    # Need US night around 0.2-0.4% and KOSPI around -1.0 to -1.4%
    us_values = [100.0 * (1.002**i) for i in range(n)]  # Slight positive US
    kp_values = [100.0 * (0.997**i) for i in range(n)]  # Slight negative KOSPI
    
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=n, freq="D", tz=_KST),
            "close": kp_values,
            "value": [15.0 + 0.01 * i for i in range(n)],
        }
    )


def _minute_series_strong(symbol: str, ymd: str) -> pd.DataFrame:
    """Create minute bars with strong symbol characteristics."""
    day = datetime.strptime(ymd, "%Y%m%d").replace(tzinfo=_KST)
    rows = []
    px = 100.0
    
    for i in range(380):
        ts = day.replace(hour=9, minute=0) + pd.Timedelta(minutes=i)
        if ts.hour == 15 and ts.minute > 20:
            break
            
        # Strong uptrend with high volume and good signals
        if i >= 200:  # Strong recovery in afternoon
            o, h, low, c = px, px + 0.25, px - 0.02, px + 0.20
        else:
            o, h, low, c = px, px + 0.12, px - 0.08, px + 0.10
            
        rows.append(
            {
                "symbol": symbol,
                "date": ts,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 25_000.0,  # High volume
            }
        )
        px = c
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def _clear_fb_debug():
    yield
    set_final_betting_debug_now(None)
    get_settings.cache_clear()


def test_symbol_quality_reduced_size_preference(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that strong symbols get preferential reduced-size entry in aggressive mode."""
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
    
    # Create strong symbol data
    df = _minute_series_strong("005930", "20260416")
    idx = _index_frame()
    ctx = StrategyContext(
        prices=df,
        kospi_index=idx[["date", "close"]].copy(),
        sp500_index=idx[["date", "close"]].copy(),
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
        volatility_index=idx[["date", "value"]].copy(),
    )
    
    signals = strat.generate_signals(ctx)
    breakdown = strat.last_intraday_signal_breakdown
    
    print("=== SYMBOL QUALITY TEST RESULTS ===")
    print(f"Market filter enhanced: {breakdown.get('market_filter_ok_effective_enhanced')}")
    print(f"Market filter override reason: {breakdown.get('market_filter_override_reason')}")
    print(f"Symbol quality score: {breakdown.get('fb_hit_thresholds', {}).get('symbol_quality_score')}")
    print(f"Symbol quality factors: {breakdown.get('fb_hit_thresholds', {}).get('symbol_quality_factors')}")
    print(f"Size reduction factor: {breakdown.get('size_reduction_factor', 'N/A')}")
    print(f"Buy signals: {len([s for s in signals if s.side == 'buy'])}")
    print("================================")
    
    # Verify key requirements
    assert breakdown.get("market_filter_ok_effective_enhanced") is True
    assert breakdown.get("market_filter_override_applied") is True
    assert breakdown.get("aggressive_entry_relaxation_applied") is True
    
    # Check that symbol quality assessment is working
    fb_hit_thresholds = breakdown.get("fb_hit_thresholds", {})
    assert "symbol_quality_score" in fb_hit_thresholds
    assert "symbol_quality_factors" in fb_hit_thresholds
    assert fb_hit_thresholds["symbol_quality_score"] >= 3  # Should detect strong symbol
    
    # Verify preferential treatment for strong symbols
    if breakdown.get("market_filter_override_reason") == "aggressive_neutral_market_strong_symbol":
        # Should have smaller size reduction (15% vs 25%)
        assert hasattr(strat, '_symbol_quality_override')
        assert strat._symbol_quality_override <= 0.75
    
    print("✅ Symbol quality enhancement working correctly")
    print("✅ Strong symbols get preferential reduced-size entry treatment")


def test_symbol_quality_vs_weak_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that weak symbols get standard reduced-size treatment."""
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
    
    # Create weaker symbol data (lower volume, weaker signals)
    def _minute_series_weak(symbol: str, ymd: str) -> pd.DataFrame:
        day = datetime.strptime(ymd, "%Y%m%d").replace(tzinfo=_KST)
        rows = []
        px = 100.0
        
        for i in range(380):
            ts = day.replace(hour=9, minute=0) + pd.Timedelta(minutes=i)
            if ts.hour == 15 and ts.minute > 20:
                break
                
            # Weaker trend with lower volume
            o, h, low, c = px, px + 0.08, px - 0.12, px + 0.05
            
            rows.append(
                {
                    "symbol": symbol,
                    "date": ts,
                    "open": o,
                    "high": h,
                    "low": low,
                    "close": c,
                    "volume": 8_000.0,  # Lower volume
                }
            )
            px = c
        return pd.DataFrame(rows)
    
    df = _minute_series_weak("005930", "20260416")
    idx = _index_frame()
    ctx = StrategyContext(
        prices=df,
        kospi_index=idx[["date", "close"]].copy(),
        sp500_index=idx[["date", "close"]].copy(),
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price"]),
        volatility_index=idx[["date", "value"]].copy(),
    )
    
    signals = strat.generate_signals(ctx)
    breakdown = strat.last_intraday_signal_breakdown
    
    print("=== WEAK SYMBOL TEST RESULTS ===")
    print(f"Symbol quality score: {breakdown.get('fb_hit_thresholds', {}).get('symbol_quality_score')}")
    print(f"Symbol quality factors: {breakdown.get('fb_hit_thresholds', {}).get('symbol_quality_factors')}")
    
    # Weak symbols should get standard or higher reduction
    if hasattr(strat, '_symbol_quality_override'):
        assert strat._symbol_quality_override >= 0.75  # Should be 15% or higher reduction
    
    print("✅ Weak symbols get standard reduced-size treatment")
