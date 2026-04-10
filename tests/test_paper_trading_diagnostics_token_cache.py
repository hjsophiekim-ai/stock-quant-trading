from __future__ import annotations

from backend.app.engine.paper_session_controller import PaperSessionController


def test_diagnostics_payload_includes_token_ensure_fields() -> None:
    c = PaperSessionController()
    c._paper_token_ensure_meta = {
        "token_cache_hit": True,
        "token_cache_source": "db",
        "token_cache_persisted": True,
        "cache_miss_reason": None,
        "start_blocked_reason": None,
        "token_error_code": None,
    }
    c._paper_diagnostics = {"token_source": "memory"}
    d = c.diagnostics_payload()
    assert d.get("token_cache_source") == "db"
    assert d.get("token_cache_persisted") is True

    c2 = PaperSessionController()
    c2._paper_token_ensure_meta = {
        "token_cache_hit": False,
        "token_cache_source": "",
        "token_cache_persisted": False,
        "cache_miss_reason": "no_cached_token",
        "start_blocked_reason": "blocked",
        "token_error_code": "TOKEN_RATE_LIMIT",
    }
    c2._paper_diagnostics = {}
    d2 = c2.diagnostics_payload()
    assert d2.get("start_blocked_reason") == "blocked"
    assert d2.get("token_error_code") == "TOKEN_RATE_LIMIT"
