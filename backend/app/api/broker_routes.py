from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from ..auth.kis_auth import issue_access_token, validate_kis_inputs
from ..api.auth_routes import get_current_user_from_auth_header
from ..core.config import get_backend_settings
from ..models.broker_account import (
    BrokerAccountResponse,
    BrokerAccountUpsertRequest,
    BrokerConnectionTestResponse,
)
from ..models.user import UserPublic
from ..services.broker_secret_service import BrokerSecretService

router = APIRouter(prefix="/broker-accounts", tags=["broker-accounts"])

_settings = get_backend_settings()
_broker_service = BrokerSecretService(
    db_path="./backend_data/broker_accounts.db",
    encryption_seed=_settings.app_secret_key or "dev-change-me",
    kis_base_url=_settings.kis_base_url if hasattr(_settings, "kis_base_url") else "https://openapi.koreainvestment.com:9443",
)


def _current_user(authorization: str | None) -> UserPublic:
    try:
        return get_current_user_from_auth_header(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except HTTPException:
        raise


@router.get("/me", response_model=BrokerAccountResponse)
def get_my_broker_account(authorization: str | None = Header(default=None)) -> BrokerAccountResponse:
    user = _current_user(authorization)
    try:
        return _broker_service.get_account(user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/me", response_model=BrokerAccountResponse)
def upsert_my_broker_account(
    payload: BrokerAccountUpsertRequest,
    authorization: str | None = Header(default=None),
) -> BrokerAccountResponse:
    user = _current_user(authorization)
    try:
        return _broker_service.upsert_account(user.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/me")
def delete_my_broker_account(authorization: str | None = Header(default=None)) -> dict[str, str]:
    user = _current_user(authorization)
    _broker_service.delete_account(user.id)
    return {"status": "deleted"}


@router.post("/me/test-connection", response_model=BrokerConnectionTestResponse)
def test_my_connection(authorization: str | None = Header(default=None)) -> BrokerConnectionTestResponse:
    user = _current_user(authorization)
    try:
        return _broker_service.test_connection(user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/me/status")
def get_my_broker_status(authorization: str | None = Header(default=None)) -> dict[str, str | bool | None]:
    user = _current_user(authorization)
    try:
        account = _broker_service.get_account(user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {
        "ok": account.connection_status == "success",
        "connection_status": account.connection_status,
        "connection_message": account.connection_message,
        "trading_mode": account.trading_mode,
        "last_tested_at": account.last_tested_at.isoformat() if account.last_tested_at else None,
    }


@router.post("/runtime/test-connection")
def test_runtime_connection() -> dict[str, str | bool]:
    cfg = get_backend_settings()
    validation_issues = validate_kis_inputs(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        account_no="00000000",
        account_product_code="01",
        base_url=cfg.kis_base_url,
    )
    # runtime token test does not require account format; keep only env/base checks.
    validation_issues = [x for x in validation_issues if "계좌" not in x]
    if validation_issues:
        return {"ok": False, "message": " / ".join(validation_issues), "error_code": "RUNTIME_ENV_INVALID"}

    token_result = issue_access_token(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        base_url=cfg.kis_base_url,
        timeout_sec=8,
    )
    return {"ok": token_result.ok, "message": token_result.message, "error_code": token_result.error_code}
