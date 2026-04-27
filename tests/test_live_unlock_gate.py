"""live unlock gate — 데이터만으로 단위 검증."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.app.risk.live_unlock_gate import evaluate_paper_readiness, paper_readiness_data_health


def _write_pnl_row(p: Path, ts: datetime, equity: float, daily: float) -> None:
    line = (
        json_line(
            {
                "ts_utc": ts.isoformat(),
                "equity": equity,
                "daily_pnl_pct": daily,
            }
        )
        + "\n"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(line)


def json_line(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def _fake_cfg(root: Path, **over) -> SimpleNamespace:
    base = dict(
        live_unlock_enabled=True,
        live_unlock_bypass=False,
        live_unlock_lookback_days=30,
        live_unlock_min_pnl_samples=5,
        live_unlock_min_period_return_pct=0.0,
        live_unlock_max_mdd_pct=15.0,
        live_unlock_max_consecutive_loss_days=5,
        live_unlock_max_order_issue_rate=0.05,
        live_unlock_max_sync_failure_streak=0,
        portfolio_data_dir=str(root),
        risk_order_audit_jsonl=str(root / "audit.jsonl"),
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_gate_passes_with_clean_history(tmp_path: Path) -> None:
    root = tmp_path / "pf"
    pnl = root / "pnl_history.jsonl"
    t0 = datetime.now(timezone.utc) - timedelta(days=12)
    eq = 1_000_000.0
    for i in range(8):
        _write_pnl_row(pnl, t0 + timedelta(days=i), eq * (1.0 + 0.001 * i), 0.1)
    (root / "audit.jsonl").write_text(
        "\n".join(
            json_line(
                {
                    "decision": {"approved": True, "reason": "", "reason_code": ""},
                }
            )
            for _ in range(20)
        ),
        encoding="utf-8",
    )
    (root / "sync_failures.json").write_text('{"consecutive_failures": 0}', encoding="utf-8")

    cfg = _fake_cfg(root, live_unlock_min_pnl_samples=5)
    r = evaluate_paper_readiness(cfg)
    assert r.ok, r.user_message_ko


def test_gate_fails_without_audit(tmp_path: Path) -> None:
    root = tmp_path / "pf"
    pnl = root / "pnl_history.jsonl"
    t0 = datetime.now(timezone.utc) - timedelta(days=12)
    for i in range(8):
        _write_pnl_row(pnl, t0 + timedelta(days=i), 1_000_000.0 * (1.0 + 0.001 * i), 0.1)
    (root / "sync_failures.json").write_text('{"consecutive_failures": 0}', encoding="utf-8")

    cfg = _fake_cfg(tmp_path / "pf")
    r = evaluate_paper_readiness(cfg)
    assert not r.ok
    assert any(x.check_id == "order_issue_rate" and not x.passed for x in r.items)


def test_bypass(tmp_path: Path) -> None:
    cfg = _fake_cfg(tmp_path / "pf", live_unlock_bypass=True)
    r = evaluate_paper_readiness(cfg)
    assert r.ok and r.bypassed


def test_readiness_data_health_reports_missing_sources(tmp_path: Path) -> None:
    root = tmp_path / "pf"
    cfg = _fake_cfg(root)
    d = paper_readiness_data_health(cfg)
    assert d["pnl_rows_found"] == 0
    assert d["audit_rows_found_tail"] == 0
    assert d["overall_data_ok"] is False
