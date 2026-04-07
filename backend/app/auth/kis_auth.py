from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class KISTokenResult:
    ok: bool
    access_token: str | None
    message: str
    error_code: str
    status_code: int | None = None


def validate_kis_inputs(
    *,
    app_key: str,
    app_secret: str,
    account_no: str,
    account_product_code: str,
    base_url: str,
) -> list[str]:
    issues: list[str] = []
    if not app_key:
        issues.append("앱키 누락: KIS_APP_KEY를 확인하세요.")
    if not app_secret:
        issues.append("시크릿 누락: KIS_APP_SECRET을 확인하세요.")
    if not account_no:
        issues.append("계좌번호 누락: KIS_ACCOUNT_NO를 확인하세요.")
    if not account_product_code:
        issues.append("계좌상품코드 누락: KIS_ACCOUNT_PRODUCT_CODE를 확인하세요.")
    if account_no and (not account_no.isdigit() or len(account_no) not in {8, 10}):
        issues.append("계좌번호 형식 오류: 숫자 8자리 또는 10자리 형식을 사용하세요.")
    if account_product_code and (not account_product_code.isdigit() or len(account_product_code) != 2):
        issues.append("계좌상품코드 형식 오류: 숫자 2자리 형식을 사용하세요.")
    if not base_url.startswith("http"):
        issues.append("base url 오류: KIS_BASE_URL/KIS_MOCK_BASE_URL 형식을 확인하세요.")
    return issues


def issue_access_token(
    *,
    app_key: str,
    app_secret: str,
    base_url: str,
    timeout_sec: int = 8,
) -> KISTokenResult:
    if not app_key:
        return KISTokenResult(False, None, "앱키 누락", "MISSING_APP_KEY")
    if not app_secret:
        return KISTokenResult(False, None, "앱시크릿 누락", "MISSING_APP_SECRET")
    if not base_url.startswith("http"):
        return KISTokenResult(False, None, "base url 오류", "INVALID_BASE_URL")

    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": app_key,
                "appsecret": app_secret,
            },
            headers={"Content-Type": "application/json"},
            timeout=timeout_sec,
        )
    except requests.RequestException:
        return KISTokenResult(False, None, "토큰 발급 실패: 네트워크 또는 base url 오류", "TOKEN_REQUEST_NETWORK_ERROR")

    if response.status_code >= 400:
        return KISTokenResult(
            False,
            None,
            f"토큰 발급 실패: HTTP {response.status_code}",
            "TOKEN_HTTP_ERROR",
            status_code=response.status_code,
        )

    try:
        payload: dict[str, Any] = response.json()
    except ValueError:
        return KISTokenResult(False, None, "토큰 발급 실패: 응답 JSON 파싱 오류", "TOKEN_JSON_ERROR")

    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        msg = str(payload.get("msg1") or payload.get("error_description") or "토큰 발급 실패")
        return KISTokenResult(False, None, f"토큰 발급 실패: {msg}", "TOKEN_ISSUE_FAILED", status_code=response.status_code)
    return KISTokenResult(True, token, "토큰 발급 성공", "OK", status_code=response.status_code)
