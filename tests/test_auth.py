from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.auth.kis_auth import KISTokenAPI, KISTokenRequestError, KISTokenService
from app.auth.token_store import InMemoryTokenStore, TokenRecord


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeHTTPClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.calls = 0

    def post(self, url: str, json: dict[str, object], headers: dict[str, str] | None = None, timeout: int = 10) -> _FakeResponse:
        _ = (url, json, headers, timeout)
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return self._responses[idx]


def _make_settings() -> SimpleNamespace:
    return SimpleNamespace(
        kis_app_key="test-app-key",
        kis_app_secret="test-app-secret",
        kis_base_url="https://example.live",
        kis_mock_base_url="https://example.mock",
        trading_mode="paper",
    )


def test_request_access_token_success() -> None:
    http = _FakeHTTPClient([_FakeResponse(200, {"access_token": "tok-1", "token_type": "Bearer", "expires_in": 3600})])
    api = KISTokenAPI(base_url="https://example.mock", http_client=http)
    token = api.request_access_token("a", "b")
    assert token.access_token == "tok-1"
    assert token.token_type == "Bearer"


def test_request_access_token_failure_status() -> None:
    http = _FakeHTTPClient([_FakeResponse(500, {"msg": "error"})])
    api = KISTokenAPI(base_url="https://example.mock", http_client=http)
    with pytest.raises(KISTokenRequestError):
        api.request_access_token("a", "b")


def test_token_cache_and_refresh_flow() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store = InMemoryTokenStore()
    http = _FakeHTTPClient(
        [
            _FakeResponse(200, {"access_token": "tok-old", "token_type": "Bearer", "expires_in": 30}),
            _FakeResponse(200, {"access_token": "tok-new", "token_type": "Bearer", "expires_in": 3600}),
        ]
    )
    api = KISTokenAPI(base_url="https://example.mock", http_client=http)
    service = KISTokenService(
        settings=_make_settings(),
        token_store=store,
        token_api=api,
        now_fn=lambda: now,
        refresh_leeway_seconds=60,
    )

    first = service.get_valid_access_token()
    assert first == "tok-old"
    # cached token expires within leeway -> should refresh.
    second = service.get_valid_access_token()
    assert second == "tok-new"
    assert http.calls == 2


def test_get_valid_access_token_uses_cache_when_still_valid() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store = InMemoryTokenStore()
    store.save(TokenRecord(access_token="cached", expires_at=now + timedelta(minutes=10)))
    http = _FakeHTTPClient([_FakeResponse(200, {"access_token": "unused", "expires_in": 3600})])
    api = KISTokenAPI(base_url="https://example.mock", http_client=http)
    service = KISTokenService(
        settings=_make_settings(),
        token_store=store,
        token_api=api,
        now_fn=lambda: now,
        refresh_leeway_seconds=60,
    )
    token = service.get_valid_access_token()
    assert token == "cached"
    assert http.calls == 0
