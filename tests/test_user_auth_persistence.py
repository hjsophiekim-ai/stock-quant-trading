from __future__ import annotations

from pathlib import Path

from backend.app.auth.jwt_service import JWTConfig, JWTService
from backend.app.auth.user_auth import UserAuthService
from backend.app.models.user import UserCreate, UserLogin


def _jwt() -> JWTService:
    return JWTService(
        JWTConfig(
            secret_key="test-secret-key",
            access_ttl_minutes=30,
            refresh_ttl_days=14,
        )
    )


def test_user_auth_persists_users_and_can_reload(tmp_path: Path) -> None:
    users_path = tmp_path / "users.json"
    revoked_path = tmp_path / "revoked.json"

    svc = UserAuthService(
        jwt_service=_jwt(),
        users_store_path=str(users_path),
        revoked_store_path=str(revoked_path),
    )
    created = svc.register(
        UserCreate(
            email="persist@example.com",
            password="password-1234",
            display_name="Persist User",
            role="user",
        )
    )
    assert created.email == "persist@example.com"
    assert users_path.is_file()

    # 새 인스턴스가 같은 파일에서 사용자 데이터를 복구해야 함
    svc2 = UserAuthService(
        jwt_service=_jwt(),
        users_store_path=str(users_path),
        revoked_store_path=str(revoked_path),
    )
    login = svc2.login(UserLogin(email="persist@example.com", password="password-1234"))
    assert login.user.email == "persist@example.com"


def test_logout_revocation_persists(tmp_path: Path) -> None:
    users_path = tmp_path / "users.json"
    revoked_path = tmp_path / "revoked.json"

    svc = UserAuthService(
        jwt_service=_jwt(),
        users_store_path=str(users_path),
        revoked_store_path=str(revoked_path),
    )
    svc.register(
        UserCreate(
            email="revoke@example.com",
            password="password-1234",
            display_name="Revoke User",
            role="user",
        )
    )
    login = svc.login(UserLogin(email="revoke@example.com", password="password-1234"))
    svc.logout(login.refresh_token)
    assert revoked_path.is_file()

    # 새 인스턴스에서도 revoke 상태가 유지되어 refresh 재사용이 거절되어야 함
    svc2 = UserAuthService(
        jwt_service=_jwt(),
        users_store_path=str(users_path),
        revoked_store_path=str(revoked_path),
    )
    try:
        svc2.refresh(login.refresh_token)
        assert False, "revoked refresh token should not be accepted"
    except ValueError as exc:
        assert "revoked" in str(exc).lower()
