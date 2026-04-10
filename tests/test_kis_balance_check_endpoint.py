from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.clients.kis_client import KISClientError
from backend.app.api import debug_routes as dr
from backend.app.main import app


def test_kis_balance_check_failure_returns_context(monkeypatch) -> None:
    monkeypatch.setattr(dr, "get_current_user_from_auth_header", lambda _h: SimpleNamespace(id="u1"))

    class Svc:
        def get_plain_credentials(self, user_id: str):
            return ("k", "s", "50000000", "01", "paper")

        def _resolve_kis_api_base(self, mode: str) -> str:
            return "https://openapivts.koreainvestment.com:29443"

        def ensure_cached_token_for_paper_start(self, user_id: str):
            return SimpleNamespace(ok=True, access_token="tok", token_error_code=None, token_cache_source="memory")

    monkeypatch.setattr(dr, "get_broker_service", lambda: Svc())

    class FakeClient:
        class tr_ids:
            balance_paper = "VTTC8434R"
            balance_live = "TTTC8434R"

        class endpoints:
            get_balance = "/uapi/domestic-stock/v1/trading/inquire-balance"

        def _resolve_tr_id(self, *, paper_tr_id: str, live_tr_id: str) -> str:
            return paper_tr_id

        def get_balance(self, account_no: str, account_product_code: str):
            raise KISClientError(
                "KIS business error: ERROR : INPUT_FIELD_NAME OFL_YN | OPSQ2001",
                kis_context={
                    "path": "/uapi/domestic-stock/v1/trading/inquire-balance",
                    "tr_id": "VTTC8434R",
                    "params": {"CANO": "50****00", "ACNT_PRDT_CD": "****"},
                },
            )

    monkeypatch.setattr(dr, "build_kis_client_for_paper_user", lambda **_k: FakeClient())

    c = TestClient(app)
    r = c.get("/api/debug/kis-balance-check", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["path"] == "/uapi/domestic-stock/v1/trading/inquire-balance"
    assert body["tr_id"] == "VTTC8434R"
    assert isinstance(body.get("sanitized_params"), dict)
