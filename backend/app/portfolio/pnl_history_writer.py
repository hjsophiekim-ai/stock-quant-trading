from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import BackendSettings
from backend.app.core.storage_paths import resolve_portfolio_data_dir

_lock = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_last_row(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return None
    if not lines:
        return None
    last = lines[-1].strip()
    if not last:
        return None
    try:
        obj = json.loads(last)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def append_pnl_history_from_paper_report(
    settings: BackendSettings,
    *,
    report: dict[str, Any],
    strategy_id: str,
    paper_market: str,
    min_interval_sec: float = 45.0,
) -> dict[str, Any]:
    root = resolve_portfolio_data_dir(settings)
    p = root / "pnl_history.jsonl"
    root.mkdir(parents=True, exist_ok=True)

    equity = float(report.get("equity") or 0.0)
    daily = report.get("daily_pnl_pct_snapshot")
    if daily is None:
        daily = report.get("daily_return_pct")
    if daily is None:
        daily = report.get("daily_pnl_pct")
    try:
        daily_pct = float(daily) if daily is not None else 0.0
    except (TypeError, ValueError):
        daily_pct = 0.0

    ts = str(report.get("ts_utc") or report.get("updated_at_utc") or _utc_now_iso())

    row = {
        "ts_utc": ts,
        "equity": equity,
        "daily_pnl_pct": daily_pct,
        "source": "paper_session_tick",
        "paper_market": str(paper_market or ""),
        "strategy_id": str(strategy_id or ""),
    }

    with _lock:
        last = _read_last_row(p)
        if last and min_interval_sec > 0:
            last_ts = str(last.get("ts_utc") or "")
            try:
                dt_last = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                dt_now = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if (dt_now - dt_last).total_seconds() < float(min_interval_sec):
                    return {"ok": True, "skipped": True, "reason": "min_interval", "path": str(p)}
            except ValueError:
                pass
        try:
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as exc:
            return {"ok": False, "error": str(exc), "path": str(p)}

    return {"ok": True, "skipped": False, "path": str(p)}

