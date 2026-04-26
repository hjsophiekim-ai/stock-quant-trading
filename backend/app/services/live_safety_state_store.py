from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LiveSafetyHistoryItem:
    ts: str
    actor: str
    action: str
    reason: str


@dataclass
class LiveSafetyState:
    user_id: str
    live_trading_flag: bool = False
    secondary_confirm_flag: bool = False
    extra_approval_flag: bool = False
    live_emergency_stop: bool = False
    updated_at_utc: str = field(default_factory=_utc_now_iso)
    history: list[LiveSafetyHistoryItem] = field(default_factory=list)


class LiveSafetyStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _load_rows(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_rows(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, user_id: str) -> LiveSafetyState:
        uid = str(user_id or "")
        with _lock:
            for r in reversed(self._load_rows()):
                if str(r.get("user_id") or "") != uid:
                    continue
                try:
                    raw_hist = r.get("history") or []
                    hist: list[LiveSafetyHistoryItem] = []
                    if isinstance(raw_hist, list):
                        for h in raw_hist:
                            if not isinstance(h, dict):
                                continue
                            ts = str(h.get("ts") or h.get("ts_utc") or "")
                            actor = str(h.get("actor") or "")
                            action = str(h.get("action") or "")
                            reason = str(h.get("reason") or "")
                            if ts and actor and action:
                                hist.append(LiveSafetyHistoryItem(ts=ts, actor=actor, action=action, reason=reason))
                    return LiveSafetyState(
                        user_id=str(r.get("user_id") or uid),
                        live_trading_flag=bool(r.get("live_trading_flag")),
                        secondary_confirm_flag=bool(r.get("secondary_confirm_flag")),
                        extra_approval_flag=bool(r.get("extra_approval_flag")),
                        live_emergency_stop=bool(r.get("live_emergency_stop")),
                        updated_at_utc=str(r.get("updated_at_utc") or _utc_now_iso()),
                        history=hist,
                    )
                except TypeError:
                    break
        return LiveSafetyState(user_id=uid)

    def upsert(self, state: LiveSafetyState) -> None:
        raw = asdict(state)
        uid = str(state.user_id or "")
        with _lock:
            rows = self._load_rows()
            found = False
            for i, r in enumerate(rows):
                if str(r.get("user_id") or "") == uid:
                    rows[i] = raw
                    found = True
                    break
            if not found:
                rows.append(raw)
            self._save_rows(rows[-500:])

