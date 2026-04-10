from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.auth.kis_auth import KISTokenResult
from backend.app.models.broker_account import BrokerAccountUpsertRequest
from backend.app.services.broker_secret_service import BrokerSecretService


@pytest.fixture()
def broker_svc(tmp_path: Path) -> BrokerSecretService:
    db = tmp_path / "broker.db"
    return BrokerSecretService(
        db_path=str(db),
        encryption_seed="test-seed-for-token-persist-16",
        kis_base_url="https://openapi.koreainvestment.com:9443",
        kis_mock_base_url="https://openapivts.koreainvestment.com:29443",
        timeout_sec=5,
    )


def test_test_connection_persists_encrypted_token_then_hydrates_new_instance(
    broker_svc: BrokerSecretService, monkeypatch: pytest.MonkeyPatch
) -> None:
    req = BrokerAccountUpsertRequest(
        kis_app_key="A" * 36,
        kis_app_secret="S" * 36,
        kis_account_no="12345678",
        kis_account_product_code="01",
        trading_mode="paper",
    )
    broker_svc.upsert_account("user-1", req)

    def fake_issue(*_a, **_k):
        return KISTokenResult(True, "persisted-access-token-xyz", "ok", "OK", 200)

    monkeypatch.setattr("backend.app.services.broker_secret_service.issue_access_token", fake_issue)
    r = broker_svc.test_connection("user-1")
    assert r.ok is True

    with broker_svc._connect() as conn:
        row = conn.execute(
            "SELECT cached_access_token_enc, cached_token_issued_at FROM broker_accounts WHERE user_id = ?",
            ("user-1",),
        ).fetchone()
    assert row["cached_access_token_enc"]
    assert row["cached_token_issued_at"]

    svc2 = BrokerSecretService(
        db_path=broker_svc.db_path,
        encryption_seed=broker_svc.encryption_seed,
        kis_base_url=broker_svc.kis_base_url,
        kis_mock_base_url=broker_svc.kis_mock_base_url,
    )
    key, _s, _a, _p, mode = svc2.get_plain_credentials("user-1")
    api_base = svc2._resolve_kis_api_base(mode)
    tok = svc2.get_cached_token(
        user_id="user-1",
        trading_mode=mode,
        api_base=api_base,
        app_key=key,
    )
    assert tok == "persisted-access-token-xyz"


def test_upsert_clears_persisted_token_columns(broker_svc: BrokerSecretService, monkeypatch: pytest.MonkeyPatch) -> None:
    req = BrokerAccountUpsertRequest(
        kis_app_key="A" * 36,
        kis_app_secret="S" * 36,
        kis_account_no="12345678",
        kis_account_product_code="01",
        trading_mode="paper",
    )
    broker_svc.upsert_account("user-2", req)
    monkeypatch.setattr(
        "backend.app.services.broker_secret_service.issue_access_token",
        lambda *_a, **_k: KISTokenResult(True, "tok", "ok", "OK", 200),
    )
    broker_svc.test_connection("user-2")

    broker_svc.upsert_account("user-2", req)
    with broker_svc._connect() as conn:
        row = conn.execute(
            "SELECT cached_access_token_enc FROM broker_accounts WHERE user_id = ?",
            ("user-2",),
        ).fetchone()
    assert row["cached_access_token_enc"] is None
