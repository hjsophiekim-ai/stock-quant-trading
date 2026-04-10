from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.api import paper_trading_routes as ptr
from backend.app.main import app


def test_paper_start_blocks_when_balance_preflight_fails(monkeypatch) -> None:
    monkeypatch.setattr(ptr, "_paper_user", lambda _a: SimpleNamespace(id="u1"))
    monkeypatch.setattr(ptr, "_require_broker_ready_for_start", lambda _u: None)
    monkeypatch.setattr(
        ptr,
        "_run_balance_preflight",
        lambda _u: {
            "ok": False,
            "failure_kind": "kis_error",
            "error": "KIS business error: ERROR : INPUT_FIELD_NAME OFL_YN | OPSQ2001",
            "path": "/uapi/domestic-stock/v1/trading/inquire-balance",
            "tr_id": "VTTC8434R",
            "sanitized_params": {"CANO": "50****00"},
        },
    )

    class Ctrl:
        def start(self, user_id: str, strategy_id: str):
            raise AssertionError("start must not be called when preflight fails")

    monkeypatch.setattr(ptr, "get_paper_session_controller", lambda: Ctrl())

    c = TestClient(app)
    r = c.post(
        "/api/paper-trading/start",
        json={"strategy_id": "swing_v1"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["code"] == "PAPER_BALANCE_PREFLIGHT_FAILED"
    assert detail["path"] == "/uapi/domestic-stock/v1/trading/inquire-balance"
    assert detail["tr_id"] == "VTTC8434R"
