from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger("backend.app.auth.kis_auth")


@dataclass(frozen=True)
class KISTokenResult:
    ok: bool
    access_token: str | None
    message: str
    error_code: str
    status_code: int | None = None


def classify_token_issue_error(*, status_code: int | None, detail_msg: str) -> str:
    """
    KIS 토큰 발급 HTTP 403 중 '1분당 1회' 등은 TOKEN_RATE_LIMIT 으로 분류.
    """
    if status_code != 403:
        return "TOKEN_HTTP_ERROR"
    d = detail_msg or ""
    if (
        "1분" in d
        or "1 분" in d
        or "잠시 후" in d
        or "잠시후" in d
        or "접근토큰" in d
        or "1회" in d
        or "rate limit" in d.lower()
        or "too many" in d.lower()
    ):
        return "TOKEN_RATE_LIMIT"
    return "TOKEN_HTTP_ERROR"


def mask_secret_tail(value: str, *, keep_last: int = 4) -> str:
    """로그용: 앱키·시크릿·토큰 전체를 남기지 않을 때 사용."""
    if not value:
        return ""
    if len(value) <= keep_last:
        return "*" * len(value)
    return "*" * (len(value) - keep_last) + value[-keep_last:]


def validate_kis_inputs(
    *,
    app_key: str,
    app_secret: str,
    account_no: str,
    account_product_code: str,
    base_url: str,
    require_account: bool = True,
) -> list[str]:
    issues: list[str] = []
    if not app_key:
        issues.append("앱키 누락: KIS_APP_KEY를 확인하세요.")
    if not app_secret:
        issues.append("시크릿 누락: KIS_APP_SECRET을 확인하세요.")
    if require_account:
        if not account_no:
            issues.append("계좌번호 누락: KIS_ACCOUNT_NO를 확인하세요.")
        if not account_product_code:
            issues.append("계좌상품코드 누락: KIS_ACCOUNT_PRODUCT_CODE를 확인하세요.")
    if account_no and (not account_no.isdigit() or len(account_no) not in {8, 10}):
        issues.append("계좌번호 형식 오류: 숫자 8자리 또는 10자리 형식을 사용하세요.")
    if account_product_code and (not account_product_code.isdigit() or len(account_product_code) != 2):
        issues.append("계좌상품코드 형식 오류: 숫자 2자리 형식을 사용하세요.")
    if not base_url.startswith("http"):
        issues.append("base url 오류: KIS_BASE_URL / KIS_MOCK_BASE_URL 형식을 확인하세요.")
    return issues


def issue_access_token(
    *,
    app_key: str,
    app_secret: str,
    base_url: str,
    timeout_sec: int = 10,
    max_retries: int = 2,
    retry_backoff_sec: float = 0.45,
) -> KISTokenResult:
    """
    KIS OAuth2 client_credentials (POST .../oauth2/tokenP).
    - HTTP 5xx·네트워크 오류 시 제한적 재시도
    - 본문 rt_cd 가 0이 아니면 실패 처리 (HTTP 200 이더라도)
    """
    if not app_key:
        return KISTokenResult(False, None, "앱키 누락", "MISSING_APP_KEY")
    if not app_secret:
        return KISTokenResult(False, None, "앱시크릿 누락", "MISSING_APP_SECRET")
    if not base_url.startswith("http"):
        return KISTokenResult(False, None, "base url 오류", "INVALID_BASE_URL")

    endpoint = f"{base_url.rstrip('/')}/oauth2/tokenP"
    payload_json = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }
    headers = {"Content-Type": "application/json; charset=UTF-8"}

    last_network: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                endpoint,
                json=payload_json,
                headers=headers,
                timeout=timeout_sec,
            )
        except requests.RequestException as exc:
            last_network = exc
            logger.warning(
                "KIS token request network error (attempt %s/%s) app_key_tail=%s",
                attempt + 1,
                max_retries + 1,
                mask_secret_tail(app_key),
            )
            if attempt >= max_retries:
                return KISTokenResult(
                    False,
                    None,
                    "토큰 발급 실패: 네트워크 또는 타임아웃",
                    "TOKEN_REQUEST_NETWORK_ERROR",
                )
            time.sleep(retry_backoff_sec * (2**attempt))
            continue

        if response.status_code >= 500:
            logger.warning(
                "KIS token HTTP %s (attempt %s) app_key_tail=%s",
                response.status_code,
                attempt + 1,
                mask_secret_tail(app_key),
            )
            if attempt < max_retries:
                time.sleep(retry_backoff_sec * (2**attempt))
                continue
            return KISTokenResult(
                False,
                None,
                f"토큰 발급 실패: HTTP {response.status_code}",
                "TOKEN_HTTP_ERROR",
                status_code=response.status_code,
            )

        if response.status_code >= 400:
            detail_msg = ""
            try:
                body: dict[str, Any] = response.json()
                detail_msg = str(body.get("msg1") or body.get("error_description") or body.get("msg") or "").strip()
            except ValueError:
                detail_msg = ""
            err_code = classify_token_issue_error(status_code=response.status_code, detail_msg=detail_msg)
            # 403은 대부분 모의/실전 도메인-키 조합 불일치 또는 권한/등록 상태 문제다.
            hint = ""
            if response.status_code == 403 and err_code != "TOKEN_RATE_LIMIT":
                hint = " (모의/실전 도메인·앱키 조합 또는 API 권한 상태 확인)"
            elif err_code == "TOKEN_RATE_LIMIT":
                hint = " (KIS 접근토큰 발급 빈도 제한 — 잠시 후 재시도)"
            suffix = f" - {detail_msg}" if detail_msg else ""
            return KISTokenResult(
                False,
                None,
                f"토큰 발급 실패: HTTP {response.status_code}{suffix}{hint}",
                err_code,
                status_code=response.status_code,
            )

        try:
            body: dict[str, Any] = response.json()
        except ValueError:
            return KISTokenResult(False, None, "토큰 발급 실패: 응답 JSON 파싱 오류", "TOKEN_JSON_ERROR")

        rt = str(body.get("rt_cd", "0"))
        if rt not in {"0", ""}:
            msg = str(body.get("msg1") or body.get("error_description") or "토큰 거절")
            return KISTokenResult(
                False,
                None,
                f"토큰 발급 실패: {msg}",
                "TOKEN_BUSINESS_ERROR",
                status_code=response.status_code,
            )

        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            msg = str(body.get("msg1") or body.get("error_description") or "access_token 없음")
            return KISTokenResult(False, None, f"토큰 발급 실패: {msg}", "TOKEN_ISSUE_FAILED")

        logger.info("KIS access token issued (app_key_tail=%s)", mask_secret_tail(app_key))
        return KISTokenResult(True, token, "토큰 발급 성공", "OK", status_code=response.status_code)

    return KISTokenResult(
        False,
        None,
        f"토큰 발급 실패: {last_network!r}",
        "TOKEN_REQUEST_NETWORK_ERROR",
    )
