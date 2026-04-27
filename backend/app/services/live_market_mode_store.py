from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.strategy.market_mode_engine import normalize_manual_mode

_lock = threading.Lock()


class LiveMarketModeStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"version": 1, "users": {}}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {"version": 1, "users": {}}
            users = raw.get("users")
            if not isinstance(users, dict):
                return {"version": 1, "users": {}}
            return {"version": int(raw.get("version") or 1), "users": users}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {"version": 1, "users": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, user_id: str, *, market: str) -> str:
        uid = str(user_id or "").strip()
        slot = "us" if str(market or "").strip().lower() == "us" else "domestic"
        if not uid:
            return "auto"
        with _lock:
            data = self._load()
            users = data.get("users") if isinstance(data.get("users"), dict) else {}
            cur = users.get(uid) if isinstance(users, dict) else None
            if isinstance(cur, dict):
                m = cur.get(slot)
            else:
                m = cur
        return normalize_manual_mode(str(m or "auto"))

    def set(self, user_id: str, *, market: str, manual_market_mode: str) -> str:
        uid = str(user_id or "").strip()
        slot = "us" if str(market or "").strip().lower() == "us" else "domestic"
        if not uid:
            return "auto"
        m = normalize_manual_mode(manual_market_mode)
        with _lock:
            data = self._load()
            users = data.get("users") if isinstance(data.get("users"), dict) else {}
            if not isinstance(users, dict):
                users = {}
            cur = users.get(uid)
            if not isinstance(cur, dict):
                cur = {}
            cur = {**cur, slot: m}
            users[uid] = cur
            data["users"] = users
            data["version"] = int(data.get("version") or 1)
            self._save(data)
        return m

