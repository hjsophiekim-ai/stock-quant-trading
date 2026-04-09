from __future__ import annotations

from typing import Any

from backend.app.auth.kis_auth import issue_access_token


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_issue_access_token_http_403_includes_kis_message_and_hint(monkeypatch) -> None:
    def _fake_post(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        return _FakeResponse(403, {"msg1": "모의투자 신청계좌가 아닙니다."})

    monkeypatch.setattr("backend.app.auth.kis_auth.requests.post", _fake_post)

    result = issue_access_token(
        app_key="app-key",
        app_secret="app-secret",
        base_url="https://openapivts.koreainvestment.com:29443",
        max_retries=0,
    )

    assert result.ok is False
    assert result.error_code == "TOKEN_HTTP_ERROR"
    assert result.status_code == 403
    assert "모의투자 신청계좌가 아닙니다." in result.message
    assert "모의/실전 도메인" in result.message


def test_issue_access_token_http_error_without_json_still_reports_status(monkeypatch) -> None:
    def _fake_post(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        return _FakeResponse(401, None)

    monkeypatch.setattr("backend.app.auth.kis_auth.requests.post", _fake_post)

    result = issue_access_token(
        app_key="app-key",
        app_secret="app-secret",
        base_url="https://openapi.koreainvestment.com:9443",
        max_retries=0,
    )

    assert result.ok is False
    assert result.error_code == "TOKEN_HTTP_ERROR"
    assert result.status_code == 401
    assert "HTTP 401" in result.message
