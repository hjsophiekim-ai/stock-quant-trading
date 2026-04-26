from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

CandidateStatus = Literal["candidate", "approval_pending", "approved", "submitted", "rejected"]

_lock = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LiveCandidate:
    candidate_id: str
    status: CandidateStatus
    symbol: str
    side: Literal["buy", "sell"]
    strategy_id: str
    score: float | None = None
    quantity: int = 0
    price: float | None = None
    stop_loss_pct: float | None = None
    rationale: str = ""
    risk_flags: list[str] = field(default_factory=list)
    created_at_utc: str = field(default_factory=_utc_now_iso)
    approved_at_utc: str | None = None
    approved_by: str | None = None
    submitted_at_utc: str | None = None
    submitted_by: str | None = None
    rejected_at_utc: str | None = None
    rejected_by: str | None = None
    last_error: str | None = None
    broker_order_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch_error(self, msg: str) -> None:
        self.last_error = (msg or "")[:500]


class LiveCandidateStore:
    def __init__(self, path: str | Path, *, max_records: int = 500) -> None:
        self.path = Path(path)
        self.max_records = max_records

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

    def list_all(self) -> list[LiveCandidate]:
        with _lock:
            return [LiveCandidate(**r) for r in self._load_rows()]

    def list_filtered(
        self,
        *,
        status: CandidateStatus | None = None,
        strategy_id: str | None = None,
        symbol: str | None = None,
        limit: int = 200,
    ) -> list[LiveCandidate]:
        items = self.list_all()
        out: list[LiveCandidate] = []
        for c in items:
            if status is not None and c.status != status:
                continue
            if strategy_id is not None and c.strategy_id != strategy_id:
                continue
            if symbol is not None and c.symbol != symbol:
                continue
            out.append(c)
        out.sort(key=lambda x: x.created_at_utc, reverse=True)
        return out[: max(1, min(int(limit), 500))]

    def get(self, candidate_id: str) -> LiveCandidate | None:
        with _lock:
            for r in self._load_rows():
                if r.get("candidate_id") == candidate_id:
                    return LiveCandidate(**r)
        return None

    def upsert(self, cand: LiveCandidate) -> None:
        with _lock:
            rows = self._load_rows()
            found = False
            for i, r in enumerate(rows):
                if r.get("candidate_id") == cand.candidate_id:
                    rows[i] = asdict(cand)
                    found = True
                    break
            if not found:
                rows.append(asdict(cand))
            rows = rows[-self.max_records :]
            self._save_rows(rows)

    def put_new(self, cand: LiveCandidate) -> LiveCandidate:
        self.upsert(cand)
        return cand

