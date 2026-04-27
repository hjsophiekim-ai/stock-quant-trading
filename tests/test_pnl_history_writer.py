from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.core.config import BackendSettings, get_backend_settings
from backend.app.portfolio.pnl_history_writer import append_pnl_history_from_paper_report
from backend.app.risk.live_unlock_gate import evaluate_paper_readiness


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def test_pnl_history_writer_appends_rows_readiness_can_use(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path / "portfolio"))
    get_backend_settings.cache_clear()
    cfg = BackendSettings()

    for i in range(12):
        rep = {
            "ts_utc": (datetime.now(timezone.utc) - timedelta(minutes=90 - i)).isoformat(),
            "equity": 1_000_000.0 * (1.0 + 0.0003 * i),
            "daily_pnl_pct_snapshot": 0.03 * i,
        }
        append_pnl_history_from_paper_report(
            cfg,
            report=rep,
            strategy_id="scalp_rsi_flag_hf_v1",
            paper_market="domestic",
            min_interval_sec=0.0,
        )

    p = Path(cfg.portfolio_data_dir) / "pnl_history.jsonl"
    rows = _read_jsonl(p)
    assert len(rows) >= 12
    assert all("ts_utc" in r and "equity" in r and "daily_pnl_pct" in r for r in rows)

    fake_cfg = type(
        "C",
        (),
        {
            "live_unlock_enabled": True,
            "live_unlock_bypass": False,
            "live_unlock_lookback_days": 30,
            "live_unlock_min_pnl_samples": 10,
            "live_unlock_min_period_return_pct": -99.0,
            "live_unlock_max_mdd_pct": 99.0,
            "live_unlock_max_consecutive_loss_days": 99,
            "live_unlock_max_order_issue_rate": 1.0,
            "live_unlock_max_sync_failure_streak": 99,
            "portfolio_data_dir": str(Path(cfg.portfolio_data_dir)),
            "risk_order_audit_jsonl": str(tmp_path / "audit.jsonl"),
        },
    )()
    (tmp_path / "audit.jsonl").write_text(
        "\n".join(json.dumps({"decision": {"approved": True, "reason": "", "reason_code": ""}}) for _ in range(5)),
        encoding="utf-8",
    )
    r = evaluate_paper_readiness(fake_cfg)
    assert any(x.check_id == "pnl_sample_size" and x.passed for x in r.items)

