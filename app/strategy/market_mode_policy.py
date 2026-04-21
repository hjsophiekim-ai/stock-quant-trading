"""
Central per-mode knobs for Paper strategies.

Base values remain in Settings / strategy code; this module returns *deltas* and
multipliers applied on top of those bases. See `compose_effective_policy`.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from app.config import Settings

MarketMode = Literal["aggressive", "neutral", "defensive"]
ManualMarketMode = Literal["auto", "aggressive", "neutral", "defensive"]


def _clamp(v: float, lo: float, hi: float) -> float:
    return float(min(hi, max(lo, v)))


def kospi_realized_vol_stress(kospi: pd.DataFrame) -> float:
    """Synthetic stress 8..45 when VIX proxy is flat (mock vol series)."""
    if kospi is None or kospi.empty or "close" not in kospi.columns:
        return 14.0
    s = kospi.sort_values("date")["close"].astype("float64")
    if len(s) < 8:
        return 14.0
    rets = s.pct_change().tail(25)
    rv = float(rets.std() * 100.0) if len(rets) else 0.0
    return float(_clamp(rv * 32.0 + 6.0, 8.0, 45.0))


def compose_effective_policy(*, active_mode: MarketMode, cfg: Settings) -> dict[str, Any]:
    """
    Returns nested dicts consumed by strategies + a flat `diagnostics` summary.

    Modes:
    - aggressive: easier gates, slightly larger risk budget (still capped by kill switch path).
    - neutral: baseline (zeros / 1.0 multipliers).
    - defensive: tighter gates, smaller participation.
    """
    base_fb = {
        "us_night_hard_delta": 0.0,
        "kospi_hard_delta": 0.0,
        "us_soft_delta": 0.0,
        "kospi_soft_delta": 0.0,
        "rank_pool_delta": 0,
        "max_new_positions_delta": 0,
        "rebound_score_delta": 0.0,
        "weak_rsi_max_delta": 0.0,
        "late_plunge_pct_delta": 0.0,
        "auction_instability_delta": 0.0,
        "day_high_zone_pct_delta": 0.0,
        "index_kospi_vs_ema5_block_relax": 0.0,
        "min_hits_weak_flow_delta": 0,
        "min_hits_tv_spike_delta": 0,
        "max_spread_pct_floor": None,
        "min_trade_value_mult": 1.0,
        "size_mult": 1.0,
        "min_alloc_pct_delta": 0.0,
        "max_capital_per_position_pct_delta": 0.0,
        "cooldown_scale": 1.0,
    }
    if active_mode == "aggressive":
        # Substantially more aggressive for final_betting_v1: much softer gates, larger budget,
        # significantly easier entry thresholds while keeping core safety
        fb = {
            **base_fb,
            "us_night_hard_delta": -0.58,  # Much softer US night gate (was -0.42)
            "kospi_hard_delta": -0.65,    # Much softer KOSPI gate (was -0.45)
            "us_soft_delta": -0.35,        # Softer soft gate (was -0.22)
            "kospi_soft_delta": -0.42,     # Softer soft gate (was -0.28)
            "rank_pool_delta": 6,           # Larger ranking pool (was 4)
            "max_new_positions_delta": 3,    # More positions allowed (was 2)
            "rebound_score_delta": -0.22,   # Much easier rebound entry (was -0.14)
            "weak_rsi_max_delta": 8.0,      # Higher RSI tolerance (was 5.0)
            "late_plunge_pct_delta": 0.75,   # More plunge tolerance (was 0.55)
            "auction_instability_delta": 0.45, # More auction tolerance (was 0.35)
            "day_high_zone_pct_delta": -4.5,  # Easier high zone requirement (was -3.2)
            "index_kospi_vs_ema5_block_relax": 0.35, # More EMA block relaxation (was 0.22)
            "min_hits_weak_flow_delta": -3,   # Lower hit requirements (was -2)
            "min_hits_tv_spike_delta": -2,    # Lower TV spike requirements (was -2)
            "max_spread_pct_floor": 0.75,      # Wider spread tolerance (was 0.68)
            "min_trade_value_mult": 0.82,     # Lower trade value threshold (was 0.88)
            "size_mult": 1.18,                 # Larger position sizes (was 1.12)
            "min_alloc_pct_delta": -4.0,       # Lower minimum allocation (was -3.0)
            "max_capital_per_position_pct_delta": 4.5, # Larger max per position (was 3.0)
            "cooldown_scale": 0.82,            # Faster cooldown recovery (was 0.88)
        }
    elif active_mode == "defensive":
        fb = {
            **base_fb,
            "us_night_hard_delta": 0.18,
            "kospi_hard_delta": 0.12,
            "us_soft_delta": 0.12,
            "kospi_soft_delta": 0.08,
            "rank_pool_delta": -1,
            "max_new_positions_delta": -1,
            "rebound_score_delta": 0.08,
            "weak_rsi_max_delta": -4.0,
            "late_plunge_pct_delta": -0.35,
            "auction_instability_delta": -0.22,
            "day_high_zone_pct_delta": 2.2,
            "index_kospi_vs_ema5_block_relax": -0.08,
            "min_hits_weak_flow_delta": 1,
            "min_hits_tv_spike_delta": 1,
            "max_spread_pct_floor": 0.42,
            "min_trade_value_mult": 1.08,
            "size_mult": 0.88,
            "min_alloc_pct_delta": 2.0,
            "max_capital_per_position_pct_delta": -3.0,
            "cooldown_scale": 1.08,
        }
    else:
        fb = dict(base_fb)

    rsi_hf = {
        "volume_z_delta": 0.0,
        "volume_ratio_delta": 0.0,
        "min_entry_score_delta": 0,
        "max_trades_per_symbol_delta": 0,
        "momentum_min_hits_delta": 0,
        "momentum_min_hits_late_delta": 0,
        "liquidity_volume_mult": 1.0,
        "liquidity_spread_mult": 1.0,
        "chase_candle_mult": 1.0,
        "intraday_risk_tighten": 0.92,
        "continuation_quality_threshold_delta": 0.0,
    }
    if active_mode == "aggressive":
        rsi_hf.update(
            {
                "volume_z_delta": 0.12,
                "volume_ratio_delta": -0.03,
                "min_entry_score_delta": -1,
                "max_trades_per_symbol_delta": 1,
                "momentum_min_hits_delta": -1,
                "momentum_min_hits_late_delta": -1,
                "liquidity_volume_mult": 0.94,
                "liquidity_spread_mult": 1.05,
                "chase_candle_mult": 1.06,
                "intraday_risk_tighten": 0.88,
                "continuation_quality_threshold_delta": -0.04,
            }
        )
    elif active_mode == "defensive":
        rsi_hf.update(
            {
                "volume_z_delta": -0.12,
                "volume_ratio_delta": 0.03,
                "min_entry_score_delta": 1,
                "max_trades_per_symbol_delta": -1,
                "momentum_min_hits_delta": 1,
                "momentum_min_hits_late_delta": 1,
                "liquidity_volume_mult": 1.06,
                "liquidity_spread_mult": 0.94,
                "chase_candle_mult": 0.94,
                "intraday_risk_tighten": 0.97,
                "continuation_quality_threshold_delta": 0.05,
            }
        )

    macd = {
        "macd_core_hits_required_delta": 0,
        "liquidity_mult": 1.0,
        "spread_mult": 1.0,
        "chase_mult": 1.0,
        "size_mult": 1.0,
    }
    if active_mode == "aggressive":
        macd.update(
            {
                "macd_core_hits_required_delta": -1,
                "liquidity_mult": 0.95,
                "spread_mult": 1.04,
                "chase_mult": 1.05,
                "size_mult": 1.06,
            }
        )
    elif active_mode == "defensive":
        macd.update(
            {
                "macd_core_hits_required_delta": 1,
                "liquidity_mult": 1.06,
                "spread_mult": 0.95,
                "chase_mult": 0.94,
                "size_mult": 0.9,
            }
        )

    swing_v2 = {
        "min_hits_delta": 0,
        "rsi_max_delta": 0.0,
        "vol_surge_min_delta": 0.0,
        "ranking_top_n_delta": 0,
        "size_mult": 1.0,
    }
    if active_mode == "aggressive":
        swing_v2.update(
            {
                "min_hits_delta": -1,
                "rsi_max_delta": 3.0,
                "vol_surge_min_delta": -0.05,
                "ranking_top_n_delta": 1,
                "size_mult": 1.06,
            }
        )
    elif active_mode == "defensive":
        swing_v2.update(
            {
                "min_hits_delta": 1,
                "rsi_max_delta": -3.0,
                "vol_surge_min_delta": 0.08,
                "ranking_top_n_delta": -1,
                "size_mult": 0.9,
            }
        )

    diagnostics = {
        "active_mode": active_mode,
        "final_betting": fb,
        "scalp_rsi_hf": rsi_hf,
        "scalp_macd_rsi_3m": macd,
        "swing_relaxed_v2": swing_v2,
    }
    return {"final_betting": fb, "scalp_rsi_hf": rsi_hf, "scalp_macd_rsi_3m": macd, "swing_relaxed_v2": swing_v2, "diagnostics": diagnostics}
