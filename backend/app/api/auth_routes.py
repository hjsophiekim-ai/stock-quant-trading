from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from ..auth.jwt_service import JWTConfig, JWTService
from ..auth.user_auth import UserAuthService
from ..core.config import get_backend_settings
from ..models.user import LogoutRequest, RefreshRequest, TokenPair, UserCreate, UserLogin, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])

_settings = get_backend_settings()
_jwt = JWTService(
    JWTConfig(
        secret_key=_settings.app_secret_key or "dev-only-change-me",
        access_ttl_minutes=30,
        refresh_ttl_days=14,
    )
)
_auth_service = UserAuthService(jwt_service=_jwt)


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    prefix = "bearer "
    if not authorization.lower().startswith(prefix):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization format")
    return authorization[len(prefix):].strip()


def get_auth_service() -> UserAuthService:
    return _auth_service


def get_current_user_from_auth_header(authorization: str | None) -> UserPublic:
    token = _extract_bearer_token(authorization)
    return _auth_service.get_current_user(token)


@router.post("/register", response_model=UserPublic)
def register(payload: UserCreate) -> UserPublic:
    try:
        return _auth_service.register(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/login", response_model=TokenPair)
def login(payload: UserLogin) -> TokenPair:
    try:
        return _auth_service.login(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest) -> TokenPair:
    try:
        return _auth_service.refresh(payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/logout")
def logout(payload: LogoutRequest) -> dict[str, str]:
    _auth_service.logout(payload.refresh_token)
    return {"status": "ok"}


@router.get("/me", response_model=UserPublic)
def me(authorization: str | None = Header(default=None)) -> UserPublic:
    token = _extract_bearer_token(authorization)
    try:
        return _auth_service.get_current_user(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
