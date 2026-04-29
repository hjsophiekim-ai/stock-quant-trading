from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from backend.app.engine.scheduler import now_kst

LiveAutoMode = Literal["aggressive", "auto", "passive"]


@dataclass
class LiveAutoGuardedState:
    user_id: str
    enabled: bool = False
    selected_strategy: str | None = None
    mode_by_strategy: dict[str, LiveAutoMode] = field(default_factory=dict)

    last_tick_at_utc: str | None = None
    last_eval_at_utc: str | None = None
    last_eval_strategies: list[str] = field(default_factory=list)
    last_eval_candidates: list[dict[str, Any]] = field(default_factory=list)
    submitted: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {"buys": [], "sells": []})
    last_decision: str = ""
    last_reason: str = ""

    daily_kst_date: str = ""
    daily_buy_count: int = 0
    daily_sell_count: int = 0

    updated_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LiveAutoGuardedStateStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path).resolve()
        self._lock = threading.Lock()

    def _read_all(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}

    def _write_all(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, user_id: str) -> LiveAutoGuardedState:
        uid = str(user_id or "").strip()
        if not uid:
            uid = "unknown"
        with self._lock:
            raw = self._read_all()
            row = raw.get(uid) if isinstance(raw.get(uid), dict) else {}
            st = LiveAutoGuardedState(user_id=uid)
            if isinstance(row, dict):
                st.enabled = bool(row.get("enabled", False))
                st.selected_strategy = row.get("selected_strategy") if row.get("selected_strategy") else None
                mb = row.get("mode_by_strategy") if isinstance(row.get("mode_by_strategy"), dict) else {}
                st.mode_by_strategy = {str(k): str(v) for k, v in mb.items()} if isinstance(mb, dict) else {}
                st.last_tick_at_utc = row.get("last_tick_at_utc") or None
                st.last_eval_at_utc = row.get("last_eval_at_utc") or None
                st.last_eval_strategies = list(row.get("last_eval_strategies") or [])
                st.last_eval_candidates = list(row.get("last_eval_candidates") or [])
                st.submitted = row.get("submitted") if isinstance(row.get("submitted"), dict) else {"buys": [], "sells": []}
                st.last_decision = str(row.get("last_decision") or "")
                st.last_reason = str(row.get("last_reason") or "")
                st.daily_kst_date = str(row.get("daily_kst_date") or "")
                st.daily_buy_count = int(row.get("daily_buy_count") or 0)
                st.daily_sell_count = int(row.get("daily_sell_count") or 0)
                st.updated_at_utc = str(row.get("updated_at_utc") or st.updated_at_utc)
            return st

    def upsert(self, st: LiveAutoGuardedState) -> None:
        with self._lock:
            raw = self._read_all()
            if not isinstance(raw, dict):
                raw = {}
            st.updated_at_utc = datetime.now(timezone.utc).isoformat()
            raw[str(st.user_id)] = asdict(st)
            self._write_all(raw)

    @staticmethod
    def ensure_daily_rollover(st: LiveAutoGuardedState) -> None:
        today = now_kst().strftime("%Y-%m-%d")
        if st.daily_kst_date != today:
            st.daily_kst_date = today
            st.daily_buy_count = 0
            st.daily_sell_count = 0
