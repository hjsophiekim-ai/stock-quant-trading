from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
from uuid import uuid4

from passlib.context import CryptContext

from .jwt_service import JWTService
from ..models.user import LoginResponse, TokenPair, UserCreate, UserEntity, UserLogin, UserPublic


@dataclass
class UserAuthService:
    jwt_service: JWTService
    users_store_path: str = "backend_data/users.json"
    revoked_store_path: str = "backend_data/revoked_refresh_tokens.json"
    _pwd: CryptContext = field(default_factory=lambda: CryptContext(schemes=["bcrypt"], deprecated="auto"))
    _users_by_email: Dict[str, UserEntity] = field(default_factory=dict)
    _revoked_refresh_tokens: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        users_path = Path(self.users_store_path)
        revoked_path = Path(self.revoked_store_path)
        users_path.parent.mkdir(parents=True, exist_ok=True)
        revoked_path.parent.mkdir(parents=True, exist_ok=True)

        if users_path.is_file():
            try:
                raw = json.loads(users_path.read_text(encoding="utf-8"))
                loaded: Dict[str, UserEntity] = {}
                for item in raw if isinstance(raw, list) else []:
                    user = UserEntity.model_validate(item)
                    loaded[user.email.lower()] = user
                self._users_by_email = loaded
            except (OSError, ValueError, TypeError):
                # 파일이 깨졌으면 빈 상태로 시작하되 서비스는 계속 동작
                self._users_by_email = {}

        if revoked_path.is_file():
            try:
                raw = json.loads(revoked_path.read_text(encoding="utf-8"))
                self._revoked_refresh_tokens = set(raw if isinstance(raw, list) else [])
            except (OSError, ValueError, TypeError):
                self._revoked_refresh_tokens = set()

    def _persist_users(self) -> None:
        p = Path(self.users_store_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        serializable = [
            user.model_dump(mode="json")
            for user in sorted(self._users_by_email.values(), key=lambda u: (u.email, u.id))
        ]
        p.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")

    def _persist_revoked(self) -> None:
        p = Path(self.revoked_store_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sorted(self._revoked_refresh_tokens), ensure_ascii=False, indent=2), encoding="utf-8")

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
        self._persist_users()
        return self._to_public(user)

    def login(self, payload: UserLogin) -> LoginResponse:
        user = self._users_by_email.get(payload.email.lower())
        if user is None or not self._pwd.verify(payload.password, user.password_hash):
            raise ValueError("Invalid credentials")
        access_token, access_ttl = self.jwt_service.create_access_token(user.id, role=user.role)
        refresh_token, refresh_ttl = self.jwt_service.create_refresh_token(user.id)
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_in_sec=access_ttl,
            refresh_expires_in_sec=refresh_ttl,
            user=self._to_public(user),
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
        self._persist_revoked()
        return TokenPair(
            access_token=access_token,
            refresh_token=new_refresh,
            access_expires_in_sec=access_ttl,
            refresh_expires_in_sec=refresh_ttl,
        )

    def logout(self, refresh_token: str) -> None:
        self._revoked_refresh_tokens.add(refresh_token)
        self._persist_revoked()

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
