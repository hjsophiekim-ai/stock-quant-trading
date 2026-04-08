import json
from pathlib import Path

from app.scheduler.equity_tracker import EquityTracker


def test_equity_tracker_daily_reset(tmp_path: Path) -> None:
    p = tmp_path / "eq.json"
    t = EquityTracker(p)
    d1, tot1 = t.pnl_snapshot(1_000_000.0)
    assert d1 == 0.0 and tot1 == 0.0
    d2, tot2 = t.pnl_snapshot(990_000.0)
    assert d2 < 0
    assert tot2 < 0

    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["baseline_equity"] == 1_000_000.0
