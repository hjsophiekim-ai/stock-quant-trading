from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from jose import JWTError, jwt


@dataclass(frozen=True)
class JWTConfig:
    secret_key: str
    algorithm: str = "HS256"
    access_ttl_minutes: int = 30
    refresh_ttl_days: int = 14
    issuer: str = "stock-quant-backend"


class JWTService:
    def __init__(self, config: JWTConfig) -> None:
        if not config.secret_key:
            raise ValueError("JWT secret key is required")
        self.config = config

    def create_access_token(self, subject: str, *, role: str, extra: dict[str, Any] | None = None) -> tuple[str, int]:
        expires = datetime.now(timezone.utc) + timedelta(minutes=self.config.access_ttl_minutes)
        payload = {
            "sub": subject,
            "role": role,
            "type": "access",
            "iss": self.config.issuer,
            "jti": str(uuid4()),
            "exp": int(expires.timestamp()),
        }
        if extra:
            payload.update(extra)
        token = jwt.encode(payload, self.config.secret_key, algorithm=self.config.algorithm)
        return token, self.config.access_ttl_minutes * 60

    def create_refresh_token(self, subject: str) -> tuple[str, int]:
        expires = datetime.now(timezone.utc) + timedelta(days=self.config.refresh_ttl_days)
        payload = {
            "sub": subject,
            "type": "refresh",
            "iss": self.config.issuer,
            "jti": str(uuid4()),
            "exp": int(expires.timestamp()),
        }
        token = jwt.encode(payload, self.config.secret_key, algorithm=self.config.algorithm)
        return token, self.config.refresh_ttl_days * 24 * 60 * 60

    def decode(self, token: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(
                token,
                self.config.secret_key,
                algorithms=[self.config.algorithm],
                options={"verify_aud": False},
            )
        except JWTError as exc:
            raise ValueError("Invalid or expired token") from exc
        return payload
