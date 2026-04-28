from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _TokRes:
    ok: bool
    access_token: str | None
    token_cache_hit: bool = False
    token_cache_source: str = ""
    token_cache_persisted: bool = False
    cache_miss_reason: str | None = None
    token_error_code: str | None = None
    message: str = ""
    failure_code: str | None = None


class _Svc:
    def __init__(self):
        self.calls = 0

    def ensure_cached_token_for_paper_start(self, _user_id: str):
        self.calls += 1
        return _TokRes(
            ok=False,
            access_token=None,
            token_error_code="TOKEN_RATE_LIMIT",
            message="rate limited",
            failure_code="PAPER_TOKEN_NOT_READY",
        )


def test_readiness_builder_token_rate_limit_backoff_skips_immediate_retry(monkeypatch, tmp_path) -> None:
    from backend.app.core.config import BackendSettings
    from backend.app.engine import live_readiness_builder as rb
    import backend.app.portfolio.sync_engine as se

    cfg = BackendSettings(
        backend_data_dir=str(tmp_path / "bd"),
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
        readiness_builder_try_start_paper_session=False,
    )

    svc = _Svc()
    monkeypatch.setattr(rb, "paper_readiness_data_health", lambda _cfg: {"pnl_rows_found": 0, "audit_rows_found_tail": 0})
    monkeypatch.setattr(rb, "evaluate_paper_readiness", lambda _cfg: type("X", (), {"ok": False})())

    monkeypatch.setattr(se, "run_portfolio_sync", lambda *a, **k: None)

    t0 = rb.tick_readiness_builder_once(cfg=cfg, broker_service=svc, user_id="u1")
    assert t0["ok"] is True
    assert svc.calls == 1
    lad = t0["state"].get("last_action_detail") or {}
    det = (lad.get("detail") or {}) if isinstance(lad, dict) else {}
    assert det.get("token_error_code") == "TOKEN_RATE_LIMIT"
    assert det.get("next_retry_at_utc")

    t1 = rb.tick_readiness_builder_once(cfg=cfg, broker_service=svc, user_id="u1")
    assert t1["ok"] is True
    assert svc.calls == 1
