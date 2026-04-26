from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

_lock = threading.Lock()

LiveExecStatus = Literal["running", "stopped"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LiveExecSession:
    session_id: str
    user_id: str
    status: LiveExecStatus
    strategy_id: str
    market: str
    execution_mode: str
    started_at_utc: str
    stopped_at_utc: str | None = None
    last_tick_at_utc: str | None = None
    last_tick_summary: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None
    actor: str = "user"
    reason: str = "start"
    metadata: dict[str, Any] = field(default_factory=dict)


class LiveExecSessionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def new_id(self) -> str:
        return str(uuid.uuid4())

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

    def get_active(self, user_id: str) -> LiveExecSession | None:
        uid = str(user_id or "")
        with _lock:
            for r in reversed(self._load_rows()):
                if str(r.get("user_id") or "") != uid:
                    continue
                if str(r.get("status") or "") != "running":
                    continue
                try:
                    return LiveExecSession(**r)
                except TypeError:
                    return None
        return None

    def get_latest(self, user_id: str) -> LiveExecSession | None:
        uid = str(user_id or "")
        with _lock:
            for r in reversed(self._load_rows()):
                if str(r.get("user_id") or "") == uid:
                    try:
                        return LiveExecSession(**r)
                    except TypeError:
                        return None
        return None

    def list_by_user(self, user_id: str, *, limit: int = 20) -> list[LiveExecSession]:
        uid = str(user_id or "")
        out: list[LiveExecSession] = []
        with _lock:
            for r in reversed(self._load_rows()):
                if str(r.get("user_id") or "") != uid:
                    continue
                try:
                    out.append(LiveExecSession(**r))
                except TypeError:
                    continue
                if len(out) >= max(1, min(int(limit), 100)):
                    break
        return out

    def upsert(self, session: LiveExecSession) -> None:
        raw = asdict(session)
        with _lock:
            rows = self._load_rows()
            found = False
            for i, r in enumerate(rows):
                if str(r.get("session_id") or "") == str(session.session_id):
                    rows[i] = raw
                    found = True
                    break
            if not found:
                rows.append(raw)
            self._save_rows(rows[-500:])

