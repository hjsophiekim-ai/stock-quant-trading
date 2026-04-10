from __future__ import annotations

from backend.app.auth.kis_auth import classify_token_issue_error, issue_access_token


def test_classify_403_korean_rate_limit_phrases() -> None:
    assert (
        classify_token_issue_error(
            status_code=403,
            detail_msg="접근토큰 발급 잠시 후 다시 시도하세요",
        )
        == "TOKEN_RATE_LIMIT"
    )
    assert classify_token_issue_error(status_code=403, detail_msg="1분당 1회만 발급") == "TOKEN_RATE_LIMIT"
    assert classify_token_issue_error(status_code=403, detail_msg="forbidden") == "TOKEN_HTTP_ERROR"


def test_issue_access_token_maps_403_rate_body_to_token_rate_limit(monkeypatch) -> None:
    class Resp:
        status_code = 403

        def json(self):
            return {"msg1": "접근토큰 발급 잠시 후 다시 시도하세요 (1분당 1회)"}

    def fake_post(*_a, **_k):
        return Resp()

    monkeypatch.setattr("backend.app.auth.kis_auth.requests.post", fake_post)
    r = issue_access_token(app_key="a" * 36, app_secret="b" * 36, base_url="https://openapivts.koreainvestment.com:29443")
    assert r.ok is False
    assert r.error_code == "TOKEN_RATE_LIMIT"
