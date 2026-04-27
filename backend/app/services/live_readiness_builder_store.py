from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LiveReadinessBuilderState:
    user_id: str
    enabled: bool = False
    started_at_utc: str | None = None
    stopped_at_utc: str | None = None
    last_tick_at_utc: str | None = None
    attempts: int = 0
    status: str | None = None
    last_action: str | None = None
    last_error: str | None = None
    last_health: dict[str, Any] = field(default_factory=dict)
    updated_at_utc: str = field(default_factory=_utc_now_iso)


_lock = threading.Lock()


class LiveReadinessBuilderStore:
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

    def get(self, user_id: str) -> LiveReadinessBuilderState:
        uid = str(user_id or "")
        with _lock:
            for r in reversed(self._load_rows()):
                if str(r.get("user_id") or "") != uid:
                    continue
                try:
                    return LiveReadinessBuilderState(
                        user_id=uid,
                        enabled=bool(r.get("enabled")),
                        started_at_utc=r.get("started_at_utc"),
                        stopped_at_utc=r.get("stopped_at_utc"),
                        last_tick_at_utc=r.get("last_tick_at_utc"),
                        attempts=int(r.get("attempts") or 0),
                        status=r.get("status"),
                        last_action=r.get("last_action"),
                        last_error=r.get("last_error"),
                        last_health=dict(r.get("last_health") or {}),
                        updated_at_utc=str(r.get("updated_at_utc") or _utc_now_iso()),
                    )
                except Exception:
                    break
        return LiveReadinessBuilderState(user_id=uid)

    def upsert(self, state: LiveReadinessBuilderState) -> None:
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

