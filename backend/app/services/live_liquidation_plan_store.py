from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

_lock = threading.Lock()

PlanStatus = Literal["prepared", "executed", "canceled"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LiquidationItem:
    symbol: str
    quantity: int
    side: Literal["sell"] = "sell"
    price: float | None = None
    est_price: float | None = None


@dataclass
class LiquidationPlan:
    plan_id: str
    user_id: str
    status: PlanStatus
    scope: str = "account_all"
    use_market_order: bool = True
    created_at_utc: str = field(default_factory=_utc_now_iso)
    created_by: str = "user"
    reason: str = "prepare"
    items: list[LiquidationItem] = field(default_factory=list)
    executed_at_utc: str | None = None
    executed_by: str | None = None
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class LiveLiquidationPlanStore:
    def __init__(self, path: str | Path, *, max_records: int = 200) -> None:
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

    def list_by_user(self, user_id: str, *, limit: int = 30) -> list[LiquidationPlan]:
        uid = str(user_id or "")
        out: list[LiquidationPlan] = []
        with _lock:
            for r in reversed(self._load_rows()):
                if str(r.get("user_id") or "") != uid:
                    continue
                try:
                    items = [LiquidationItem(**x) for x in list(r.get("items") or [])]
                    out.append(LiquidationPlan(**{**r, "items": items}))
                except TypeError:
                    continue
                if len(out) >= max(1, min(int(limit), 100)):
                    break
        return out

    def get(self, plan_id: str) -> LiquidationPlan | None:
        pid = str(plan_id or "")
        with _lock:
            for r in self._load_rows():
                if str(r.get("plan_id") or "") == pid:
                    try:
                        items = [LiquidationItem(**x) for x in list(r.get("items") or [])]
                        return LiquidationPlan(**{**r, "items": items})
                    except TypeError:
                        return None
        return None

    def upsert(self, plan: LiquidationPlan) -> None:
        with _lock:
            rows = self._load_rows()
            found = False
            raw = asdict(plan)
            raw["items"] = [asdict(x) for x in plan.items]
            for i, r in enumerate(rows):
                if str(r.get("plan_id") or "") == str(plan.plan_id):
                    rows[i] = raw
                    found = True
                    break
            if not found:
                rows.append(raw)
            rows = rows[-self.max_records :]
            self._save_rows(rows)

