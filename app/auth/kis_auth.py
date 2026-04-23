from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Callable, Protocol

import requests

from app.auth.token_store import InMemoryTokenStore, TokenRecord, TokenStore
from app.config import Settings, get_settings


class AuthHTTPClient(Protocol):
    def post(
        self,
        url: str,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout: int = 10,
    ) -> requests.Response:
        ...


class RequestsAuthHTTPClient:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def post(
        self,
        url: str,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout: int = 10,
    ) -> requests.Response:
        return self._session.post(url, json=json, headers=headers, timeout=timeout)


class KISTokenRequestError(RuntimeError):
    pass


@dataclass
class KISTokenAPI:
    base_url: str
    http_client: AuthHTTPClient
    timeout_sec: int = 10
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def request_access_token(self, app_key: str, app_secret: str) -> TokenRecord:
        endpoint = f"{self.base_url.rstrip('/')}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": app_key,
            "appsecret": app_secret,
        }
        headers = {"content-type": "application/json; charset=UTF-8"}

        try:
            response = self.http_client.post(endpoint, json=payload, headers=headers, timeout=self.timeout_sec)
        except requests.RequestException as exc:
            raise KISTokenRequestError("Network error during token request") from exc
        if response.status_code >= 400:
            raise KISTokenRequestError(f"Token request failed with status={response.status_code}")

        try:
            body = response.json()
        except ValueError as exc:
            raise KISTokenRequestError("Token response is not valid JSON") from exc

        if str(body.get("rt_cd", "0")) not in {"0", ""}:
            msg = str(body.get("msg1", "Unknown KIS token error"))
            raise KISTokenRequestError(f"KIS token rejected: {msg}")

        access_token = str(body.get("access_token", "")).strip()
        if not access_token:
            raise KISTokenRequestError("Token response missing access_token")

        token_type = str(body.get("token_type", "Bearer"))
        expires_in_raw = body.get("expires_in", 0)
        try:
            expires_in = int(expires_in_raw)
        except (TypeError, ValueError) as exc:
            raise KISTokenRequestError("Token response has invalid expires_in") from exc

        now = self.now_fn()
        expires_at = now + timedelta(seconds=max(expires_in, 0))
        return TokenRecord(access_token=access_token, expires_at=expires_at, token_type=token_type)


@dataclass
class KISTokenService:
    settings: Settings
    token_store: TokenStore
    token_api: KISTokenAPI
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    refresh_leeway_seconds: int = 60
    logger: logging.Logger = logging.getLogger("app.auth.kis_auth")

    def __post_init__(self) -> None:
        try:
            self.token_api.now_fn = self.now_fn
        except Exception:
            pass

    @classmethod
    def from_env(cls, settings: Settings | None = None) -> "KISTokenService":
        cfg = settings or get_settings()
        base_url = cls._resolve_auth_base_url(cfg)
        return cls(
            settings=cfg,
            token_store=InMemoryTokenStore(),
            token_api=KISTokenAPI(base_url=base_url, http_client=RequestsAuthHTTPClient()),
        )

    @staticmethod
    def _resolve_auth_base_url(settings: Settings) -> str:
        if settings.trading_mode == "paper":
            return settings.kis_mock_base_url or settings.kis_base_url
        return settings.kis_base_url

    def request_access_token(self) -> TokenRecord:
        if not self.settings.kis_app_key or not self.settings.kis_app_secret:
            raise KISTokenRequestError("KIS app credentials are missing")

        self.logger.info("Requesting new KIS access token")
        token = self.token_api.request_access_token(
            app_key=self.settings.kis_app_key,
            app_secret=self.settings.kis_app_secret,
        )
        self.token_store.save(token)
        self.logger.info("KIS access token issued and cached")
        return token

    def get_cached_token(self) -> TokenRecord | None:
        return self.token_store.load()

    def is_token_valid(self, token: TokenRecord | None) -> bool:
        if token is None:
            return False
        now = self.now_fn()
        return not token.will_expire_within(now, self.refresh_leeway_seconds)

    def refresh_access_token(self) -> TokenRecord:
        self.logger.info("Refreshing KIS access token")
        return self.request_access_token()

    def get_valid_access_token(self, force_refresh: bool = False) -> str:
        if force_refresh:
            return self.refresh_access_token().access_token

        cached = self.token_store.load()
        if self.is_token_valid(cached):
            return cached.access_token

        refreshed = self.refresh_access_token()
        return refreshed.access_token
