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
class SellOnlyArmState:
    user_id: str
    enabled: bool
    scope: str = "final_betting_only"
    armed_for_kst_date: str = ""
    created_at_utc: str = field(default_factory=_utc_now_iso)
    updated_at_utc: str = field(default_factory=_utc_now_iso)
    actor: str = "user"
    reason: str = "arm"
    metadata: dict[str, Any] = field(default_factory=dict)


class SellOnlyArmStore:
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

    def get(self, user_id: str) -> SellOnlyArmState | None:
        uid = str(user_id or "")
        with _lock:
            for r in self._load_rows():
                if str(r.get("user_id") or "") == uid:
                    try:
                        return SellOnlyArmState(**r)
                    except TypeError:
                        return None
        return None

    def list_enabled_for_date(self, kst_date: str) -> list[SellOnlyArmState]:
        d = str(kst_date or "")
        out: list[SellOnlyArmState] = []
        with _lock:
            for r in self._load_rows():
                if not bool(r.get("enabled")):
                    continue
                if str(r.get("armed_for_kst_date") or "") != d:
                    continue
                try:
                    out.append(SellOnlyArmState(**r))
                except TypeError:
                    continue
        return out

    def upsert(self, st: SellOnlyArmState) -> None:
        with _lock:
            rows = self._load_rows()
            found = False
            for i, r in enumerate(rows):
                if str(r.get("user_id") or "") == str(st.user_id):
                    rows[i] = asdict(st)
                    found = True
                    break
            if not found:
                rows.append(asdict(st))
            self._save_rows(rows)

