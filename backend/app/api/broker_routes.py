from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, status

from ..auth.kis_auth import issue_access_token, validate_kis_inputs
from ..api.auth_routes import get_current_user_from_auth_header
from ..core.config import get_backend_settings, resolved_kis_api_base_url
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
    kis_base_url=_settings.kis_base_url,
    kis_mock_base_url=getattr(_settings, "kis_mock_base_url", "") or "https://openapivts.koreainvestment.com:29443",
)


def get_broker_service() -> BrokerSecretService:
    """다른 라우터(예: paper-trading)에서 동일 DB·암호화 설정으로 브로커 상태를 조회할 때 사용."""
    return _broker_service


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="등록된 브로커 계정이 없습니다. 아래에서 정보를 저장한 뒤 연결 테스트를 실행하세요.",
        ) from exc


@router.post("/me", response_model=BrokerAccountResponse)
def upsert_my_broker_account(
    payload: BrokerAccountUpsertRequest,
    authorization: str | None = Header(default=None),
) -> BrokerAccountResponse:
    user = _current_user(authorization)
    try:
        return _broker_service.upsert_account(user.id, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc) or "브로커 정보를 저장할 수 없습니다. 입력값을 확인하세요.",
        ) from exc


@router.delete("/me")
def delete_my_broker_account(authorization: str | None = Header(default=None)) -> dict[str, str]:
    user = _current_user(authorization)
    _broker_service.delete_account(user.id)
    return {"status": "deleted"}


@router.post("/me/test-connection", response_model=BrokerConnectionTestResponse)
def test_my_connection(
    authorization: str | None = Header(default=None),
    market: str | None = Query(
        default=None,
        description="domestic(기본) 또는 us — us 이면 해외주식 잔고 inquire-balance(NASD/USD)로 검증",
    ),
) -> BrokerConnectionTestResponse:
    user = _current_user(authorization)
    try:
        return _broker_service.test_connection(user.id, market=market)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="먼저 브로커 정보를 저장한 뒤 연결 테스트를 실행하세요.",
        ) from None


@router.get("/me/status")
def get_my_broker_status(authorization: str | None = Header(default=None)) -> dict[str, str | bool | None]:
    user = _current_user(authorization)
    try:
        account = _broker_service.get_account(user.id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="등록된 브로커 계정이 없습니다.",
        ) from None
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
    api_base = resolved_kis_api_base_url(cfg)
    validation_issues = validate_kis_inputs(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        account_no="",
        account_product_code="",
        base_url=api_base,
        require_account=False,
    )
    if validation_issues:
        return {"ok": False, "message": " / ".join(validation_issues), "error_code": "RUNTIME_ENV_INVALID"}

    token_result = issue_access_token(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        base_url=api_base,
        timeout_sec=10,
    )
    return {
        "ok": token_result.ok,
        "message": token_result.message,
        "error_code": token_result.error_code,
        "kis_api_base": api_base,
        "trading_mode": cfg.trading_mode,
    }
