from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Protocol


@dataclass(frozen=True)
class TokenRecord:
    access_token: str
    expires_at: datetime
    token_type: str = "Bearer"

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at

    def will_expire_within(self, now: datetime, leeway_seconds: int) -> bool:
        seconds_left = (self.expires_at - now).total_seconds()
        return seconds_left <= leeway_seconds


class TokenStore(Protocol):
    def save(self, token: TokenRecord) -> None:
        ...

    def load(self) -> TokenRecord | None:
        ...

    def clear(self) -> None:
        ...


class InMemoryTokenStore:
    def __init__(self) -> None:
        self._token: TokenRecord | None = None
        self._lock = Lock()

    def save(self, token: TokenRecord) -> None:
        with self._lock:
            self._token = token

    def load(self) -> TokenRecord | None:
        with self._lock:
            return self._token

    def clear(self) -> None:
        with self._lock:
            self._token = None
