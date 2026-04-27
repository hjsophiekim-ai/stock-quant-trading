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
class LiveAutoGuardedState:
    user_id: str
    enabled: bool = False
    started_at_utc: str | None = None
    stopped_at_utc: str | None = None
    last_tick_at_utc: str | None = None
    last_decision: str | None = None
    last_reason: str | None = None
    cooldown_until_utc: str | None = None
    daily_buy_count: int = 0
    daily_sell_count: int = 0
    daily_kst_date: str | None = None
    recent_submits: dict[str, str] = field(default_factory=dict)
    updated_at_utc: str = field(default_factory=_utc_now_iso)


_lock = threading.Lock()


class LiveAutoGuardedStore:
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

    def get(self, user_id: str) -> LiveAutoGuardedState:
        uid = str(user_id or "")
        with _lock:
            for r in reversed(self._load_rows()):
                if str(r.get("user_id") or "") != uid:
                    continue
                try:
                    return LiveAutoGuardedState(
                        user_id=uid,
                        enabled=bool(r.get("enabled")),
                        started_at_utc=r.get("started_at_utc"),
                        stopped_at_utc=r.get("stopped_at_utc"),
                        last_tick_at_utc=r.get("last_tick_at_utc"),
                        last_decision=r.get("last_decision"),
                        last_reason=r.get("last_reason"),
                        cooldown_until_utc=r.get("cooldown_until_utc"),
                        daily_buy_count=int(r.get("daily_buy_count") or 0),
                        daily_sell_count=int(r.get("daily_sell_count") or 0),
                        daily_kst_date=r.get("daily_kst_date"),
                        recent_submits=dict(r.get("recent_submits") or {}),
                        updated_at_utc=str(r.get("updated_at_utc") or _utc_now_iso()),
                    )
                except Exception:
                    break
        return LiveAutoGuardedState(user_id=uid)

    def upsert(self, state: LiveAutoGuardedState) -> None:
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

    def list_enabled(self) -> list[LiveAutoGuardedState]:
        with _lock:
            rows = self._load_rows()
        out: list[LiveAutoGuardedState] = []
        for r in rows:
            if not bool(r.get("enabled")):
                continue
            uid = str(r.get("user_id") or "")
            if not uid:
                continue
            try:
                out.append(
                    LiveAutoGuardedState(
                        user_id=uid,
                        enabled=bool(r.get("enabled")),
                        started_at_utc=r.get("started_at_utc"),
                        stopped_at_utc=r.get("stopped_at_utc"),
                        last_tick_at_utc=r.get("last_tick_at_utc"),
                        last_decision=r.get("last_decision"),
                        last_reason=r.get("last_reason"),
                        cooldown_until_utc=r.get("cooldown_until_utc"),
                        daily_buy_count=int(r.get("daily_buy_count") or 0),
                        daily_sell_count=int(r.get("daily_sell_count") or 0),
                        daily_kst_date=r.get("daily_kst_date"),
                        recent_submits=dict(r.get("recent_submits") or {}),
                        updated_at_utc=str(r.get("updated_at_utc") or _utc_now_iso()),
                    )
                )
            except Exception:
                continue
        out.sort(key=lambda x: (str(x.user_id), str(x.started_at_utc or ""), str(x.updated_at_utc or "")))
        return out

