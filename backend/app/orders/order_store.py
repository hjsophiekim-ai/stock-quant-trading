"""추적 주문 영속화 (JSON, 스레드 안전)."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()


@dataclass
class TrackedOrderRecord:
    """내부 주문 ID + 브로커 주문번호 + 체결 추적."""

    order_id: str
    status: str
    symbol: str
    side: str
    quantity: int
    requested_price: float | None
    signal_id: str | None
    strategy_id: str
    broker_order_id: str = ""
    filled_quantity: int = 0
    fill_price: float | None = None
    failure_reason: str | None = None
    last_broker_message: str | None = None
    attempts: int = 0
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_masked_response_log: str | None = None

    def touch(self) -> None:
        self.updated_at_utc = datetime.now(timezone.utc).isoformat()


class TrackedOrderStore:
    def __init__(self, path: str | Path, *, max_records: int = 800) -> None:
        self.path = Path(path)
        self.max_records = max_records

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_all(self) -> list[TrackedOrderRecord]:
        with _lock:
            return [TrackedOrderRecord(**r) for r in self._load()]

    def get(self, order_id: str) -> TrackedOrderRecord | None:
        with _lock:
            for r in self._load():
                if r.get("order_id") == order_id:
                    return TrackedOrderRecord(**r)
        return None

    def upsert(self, rec: TrackedOrderRecord) -> None:
        rec.touch()
        with _lock:
            rows = self._load()
            found = False
            for i, r in enumerate(rows):
                if r.get("order_id") == rec.order_id:
                    rows[i] = asdict(rec)
                    found = True
                    break
            if not found:
                rows.append(asdict(rec))
            rows = rows[-self.max_records :]
            self._save(rows)

    def new_id(self) -> str:
        return str(uuid.uuid4())


def filter_active_submitted(records: list[TrackedOrderRecord]) -> list[TrackedOrderRecord]:
    return [r for r in records if r.status in {"submitted", "partially_filled", "approved"}]
