from __future__ import annotations

from pathlib import Path

from backend.app.models.broker_account import BrokerAccountUpsertRequest
from backend.app.services.broker_secret_service import BrokerSecretService


def _make_service(tmp_path: Path) -> BrokerSecretService:
    return BrokerSecretService(
        db_path=str(tmp_path / "broker_accounts.db"),
        encryption_seed="test-seed",
        kis_base_url="https://openapi.koreainvestment.com:9443",
        kis_mock_base_url="https://openapivts.koreainvestment.com:29443",
    )


def test_cached_token_saved_after_successful_test_connection(monkeypatch, tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    uid = "u-1"
    svc.upsert_account(
        uid,
        BrokerAccountUpsertRequest(
            kis_app_key="mock-app-key-1234",
            kis_app_secret="mock-secret-1234",
            kis_account_no="12345678",
            kis_account_product_code="01",
            trading_mode="paper",
        ),
    )

    class _OkResult:
        ok = True
        access_token = "token-from-test"
        message = "ok"
        error_code = "OK"
        status_code = 200

    monkeypatch.setattr(
        "backend.app.services.broker_secret_service.issue_access_token",
        lambda **kwargs: _OkResult(),
    )

    out = svc.test_connection(uid)
    assert out.ok is True
    tok = svc.get_cached_token(
        user_id=uid,
        trading_mode="paper",
        api_base="https://openapivts.koreainvestment.com:29443",
        app_key="mock-app-key-1234",
    )
    assert tok == "token-from-test"


def test_cached_token_cleared_when_account_upserted(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    uid = "u-2"
    svc._token_cache[uid] = {
        "token": "x",
        "issued_monotonic": 1.0,
        "mode": "paper",
        "api_base": "https://openapivts.koreainvestment.com:29443",
        "app_key_tail": "1234",
    }

    svc.upsert_account(
        uid,
        BrokerAccountUpsertRequest(
            kis_app_key="mock-app-key-1234",
            kis_app_secret="mock-secret-1234",
            kis_account_no="12345678",
            kis_account_product_code="01",
            trading_mode="paper",
        ),
    )
    assert svc.get_cached_token(
        user_id=uid,
        trading_mode="paper",
        api_base="https://openapivts.koreainvestment.com:29443",
        app_key="mock-app-key-1234",
    ) is None
