from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.engine import paper_session_controller as psc
from backend.app.services.broker_secret_service import PaperSessionTokenEnsureResult


def test_paper_start_raises_when_token_ensure_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class Svc:
        def get_account(self, user_id: str):
            return SimpleNamespace(trading_mode="paper", connection_status="success")

        def _resolve_kis_api_base(self, mode: str) -> str:
            return "https://openapivts.koreainvestment.com:29443"

        def ensure_cached_token_for_paper_start(self, user_id: str) -> PaperSessionTokenEnsureResult:
            return PaperSessionTokenEnsureResult(
                ok=False,
                access_token=None,
                token_cache_hit=False,
                token_cache_source="",
                token_cache_persisted=False,
                cache_miss_reason="no_cached_token",
                token_error_code="TOKEN_HTTP_ERROR",
                message="cannot issue",
                failure_code="PAPER_TOKEN_NOT_READY",
            )

    monkeypatch.setattr(psc, "get_broker_service", lambda: Svc())
    ctrl = psc.PaperSessionController()
    with pytest.raises(ValueError, match="PAPER_TOKEN_NOT_READY"):
        ctrl.start("u1", "swing_v1")
    snap = ctrl.paper_token_ensure_snapshot()
    assert snap.get("start_blocked_reason") == "cannot issue"


def test_paper_start_proceeds_when_ensure_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    class Svc:
        def get_account(self, user_id: str):
            return SimpleNamespace(trading_mode="paper", connection_status="success")

        def _resolve_kis_api_base(self, mode: str) -> str:
            return "https://openapivts.koreainvestment.com:29443"

        def ensure_cached_token_for_paper_start(self, user_id: str) -> PaperSessionTokenEnsureResult:
            return PaperSessionTokenEnsureResult(
                ok=True,
                access_token="cached-tok",
                token_cache_hit=True,
                token_cache_source="memory",
                token_cache_persisted=True,
                cache_miss_reason=None,
                token_error_code=None,
                message="ok",
                failure_code=None,
            )

    monkeypatch.setattr(psc, "get_broker_service", lambda: Svc())
    ctrl = psc.PaperSessionController()
    out = ctrl.start("u1", "swing_v1")
    assert out.get("ok") is True
    ctrl.stop("u1")
