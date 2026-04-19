"""backend paper_strategy — 전략 ID 매핑 스모크(레거시 + 신규)."""

from __future__ import annotations

import pytest

from backend.app.engine.paper_strategy import strategy_for_paper_id


@pytest.mark.parametrize(
    "sid",
    [
        "swing_v1",
        "swing_relaxed_v1",
        "swing_relaxed_v2",
        "bull_focus_v1",
        "defensive_v1",
        "scalp_momentum_v1",
        "scalp_momentum_v2",
        "scalp_momentum_v3",
        "scalp_macd_rsi_3m_v1",
        "scalp_rsi_flag_hf_v1",
        "final_betting_v1",
        "us_swing_relaxed_v1",
        "us_scalp_momentum_v1",
    ],
)
def test_strategy_for_paper_id_resolves(sid: str) -> None:
    s = strategy_for_paper_id(sid)
    assert s is not None
    assert type(s).__name__ != "SwingStrategy" or sid == "swing_v1"


def test_unknown_id_falls_back_to_swing() -> None:
    s = strategy_for_paper_id("totally_unknown_strategy_xyz")
    assert type(s).__name__ == "SwingStrategy"
