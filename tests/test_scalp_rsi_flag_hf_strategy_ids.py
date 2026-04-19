"""scalp_rsi_flag_hf_v1 / intraday_rsi_flag_hf_v1 동일 구현·다른 paper ID."""

from __future__ import annotations

from app.config import get_settings
from app.strategy.scalp_rsi_flag_hf_v1_strategy import ScalpRsiFlagHfV1Strategy
from app.strategy.intraday_common import effective_intraday_max_open_positions


def test_effective_max_open_positions_matches_for_hf_aliases() -> None:
    cfg = get_settings()
    a = effective_intraday_max_open_positions(cfg, "scalp_rsi_flag_hf_v1")
    b = effective_intraday_max_open_positions(cfg, "intraday_rsi_flag_hf_v1")
    assert a == b

    s1 = ScalpRsiFlagHfV1Strategy()
    setattr(s1, "_paper_strategy_id", "intraday_rsi_flag_hf_v1")
    assert effective_intraday_max_open_positions(cfg, "intraday_rsi_flag_hf_v1") == effective_intraday_max_open_positions(
        cfg, getattr(s1, "_paper_strategy_id")
    )
