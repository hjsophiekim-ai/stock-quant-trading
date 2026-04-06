from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

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
