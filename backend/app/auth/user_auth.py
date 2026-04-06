from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict
from uuid import uuid4

from passlib.context import CryptContext

from .jwt_service import JWTService
from ..models.user import TokenPair, UserCreate, UserEntity, UserLogin, UserPublic


@dataclass
class UserAuthService:
    jwt_service: JWTService
    _pwd: CryptContext = field(default_factory=lambda: CryptContext(schemes=["bcrypt"], deprecated="auto"))
    _users_by_email: Dict[str, UserEntity] = field(default_factory=dict)
    _revoked_refresh_tokens: set[str] = field(default_factory=set)

    def register(self, payload: UserCreate) -> UserPublic:
        key = payload.email.lower()
        if key in self._users_by_email:
            raise ValueError("User already exists")
        hashed = self._pwd.hash(payload.password)
        user = UserEntity(
            id=str(uuid4()),
            email=key,
            display_name=payload.display_name,
            role=payload.role,
            password_hash=hashed,
            settings={"preferred_mode": "paper"},
            broker_accounts=[],
            created_at=datetime.now(timezone.utc),
        )
        self._users_by_email[key] = user
        return self._to_public(user)

    def login(self, payload: UserLogin) -> TokenPair:
        user = self._users_by_email.get(payload.email.lower())
        if user is None or not self._pwd.verify(payload.password, user.password_hash):
            raise ValueError("Invalid credentials")
        access_token, access_ttl = self.jwt_service.create_access_token(user.id, role=user.role)
        refresh_token, refresh_ttl = self.jwt_service.create_refresh_token(user.id)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_in_sec=access_ttl,
            refresh_expires_in_sec=refresh_ttl,
        )

    def refresh(self, refresh_token: str) -> TokenPair:
        if refresh_token in self._revoked_refresh_tokens:
            raise ValueError("Refresh token revoked")
        payload = self.jwt_service.decode(refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("Invalid refresh token")
        user_id = str(payload.get("sub", ""))
        user = self._find_user_by_id(user_id)
        if user is None:
            raise ValueError("User not found")

        access_token, access_ttl = self.jwt_service.create_access_token(user.id, role=user.role)
        new_refresh, refresh_ttl = self.jwt_service.create_refresh_token(user.id)
        self._revoked_refresh_tokens.add(refresh_token)
        return TokenPair(
            access_token=access_token,
            refresh_token=new_refresh,
            access_expires_in_sec=access_ttl,
            refresh_expires_in_sec=refresh_ttl,
        )

    def logout(self, refresh_token: str) -> None:
        self._revoked_refresh_tokens.add(refresh_token)

    def get_current_user(self, access_token: str) -> UserPublic:
        payload = self.jwt_service.decode(access_token)
        if payload.get("type") != "access":
            raise ValueError("Invalid access token")
        user_id = str(payload.get("sub", ""))
        user = self._find_user_by_id(user_id)
        if user is None:
            raise ValueError("User not found")
        return self._to_public(user)

    def _find_user_by_id(self, user_id: str) -> UserEntity | None:
        for user in self._users_by_email.values():
            if user.id == user_id:
                return user
        return None

    @staticmethod
    def _to_public(user: UserEntity) -> UserPublic:
        return UserPublic(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            settings=user.settings,
            broker_accounts=user.broker_accounts,
            created_at=user.created_at,
        )
