from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")


@dataclass
class EquityTrackerState:
    """Persisted baseline for daily / cumulative PnL used by the risk engine."""

    baseline_equity: float
    baseline_at_iso: str
    day_key_kst: str
    day_open_equity: float


class EquityTracker:
    """Tracks equity at KST day boundaries and an optional long-run baseline."""

    def __init__(self, path: Path, *, logger: logging.Logger | None = None) -> None:
        self.path = path
        self.logger = logger or logging.getLogger("app.scheduler.equity_tracker")
        self._state: EquityTrackerState | None = None

    def _today_kst(self) -> str:
        return datetime.now(_KST).strftime("%Y-%m-%d")

    def load(self) -> None:
        if not self.path.is_file():
            self._state = None
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._state = EquityTrackerState(
                baseline_equity=float(raw["baseline_equity"]),
                baseline_at_iso=str(raw["baseline_at_iso"]),
                day_key_kst=str(raw["day_key_kst"]),
                day_open_equity=float(raw["day_open_equity"]),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.logger.warning("Equity tracker state unreadable; starting fresh: %s", exc)
            self._state = None

    def save(self) -> None:
        if self._state is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(self._state), indent=2), encoding="utf-8")

    def pnl_snapshot(self, equity: float, *, valid: bool = True) -> tuple[float, float]:
        """
        Returns (daily_pnl_pct, total_pnl_pct_vs_baseline).
        Negative values mean loss vs baseline / day open.
        """
        self.load()
        today = self._today_kst()
        now_iso = datetime.now(_KST).isoformat()

        if not valid:
            return 0.0, 0.0

        if self._state is None:
            self._state = EquityTrackerState(
                baseline_equity=equity,
                baseline_at_iso=now_iso,
                day_key_kst=today,
                day_open_equity=equity,
            )
            self.save()
            return 0.0, 0.0

        if self._state.day_key_kst != today:
            self._state = EquityTrackerState(
                baseline_equity=self._state.baseline_equity,
                baseline_at_iso=self._state.baseline_at_iso,
                day_key_kst=today,
                day_open_equity=equity,
            )
            self.save()

        day_open = self._state.day_open_equity if self._state.day_open_equity > 0 else 1.0
        base = self._state.baseline_equity if self._state.baseline_equity > 0 else 1.0

        daily_pct = ((equity / day_open) - 1.0) * 100.0
        total_pct = ((equity / base) - 1.0) * 100.0
        return daily_pct, total_pct
