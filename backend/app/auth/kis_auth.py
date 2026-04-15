from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger("backend.app.auth.kis_auth")

# OAuth2 토큰 엔드포인트(TR API 의 tr_id 헤더와 무관)
KIS_OAUTH_TOKEN_HTTP_PATH = "/oauth2/tokenP"
KIS_OAUTH_TR_ID_NOTE = "(oauth2/tokenP — REST TR_ID 미사용)"


@dataclass(frozen=True)
class KISTokenResult:
    ok: bool
    access_token: str | None
    message: str
    error_code: str
    status_code: int | None = None
    kis_base_url: str | None = None
    kis_http_path: str | None = None
    kis_tr_id: str | None = None


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
    tr_id = KIS_OAUTH_TR_ID_NOTE

    if not app_key:
        return KISTokenResult(
            False,
            None,
            "앱키 누락",
            "MISSING_APP_KEY",
            kis_base_url=base_url.rstrip("/") if base_url.startswith("http") else None,
            kis_http_path=KIS_OAUTH_TOKEN_HTTP_PATH,
            kis_tr_id=tr_id,
        )
    if not app_secret:
        return KISTokenResult(
            False,
            None,
            "앱시크릿 누락",
            "MISSING_APP_SECRET",
            kis_base_url=base_url.rstrip("/") if base_url.startswith("http") else None,
            kis_http_path=KIS_OAUTH_TOKEN_HTTP_PATH,
            kis_tr_id=tr_id,
        )
    if not base_url.startswith("http"):
        return KISTokenResult(
            False,
            None,
            "base url 오류",
            "INVALID_BASE_URL",
            kis_base_url=base_url,
            kis_http_path=KIS_OAUTH_TOKEN_HTTP_PATH,
            kis_tr_id=tr_id,
        )

    norm_base = base_url.rstrip("/")
    endpoint = f"{norm_base}{KIS_OAUTH_TOKEN_HTTP_PATH}"
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
                    kis_base_url=norm_base,
                    kis_http_path=KIS_OAUTH_TOKEN_HTTP_PATH,
                    kis_tr_id=tr_id,
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
                kis_base_url=norm_base,
                kis_http_path=KIS_OAUTH_TOKEN_HTTP_PATH,
                kis_tr_id=tr_id,
            )

        if response.status_code >= 400:
            logger.warning(
                "KIS token HTTP %s path=%s base=%s tr_id=%s",
                response.status_code,
                KIS_OAUTH_TOKEN_HTTP_PATH,
                norm_base,
                tr_id,
            )
            return KISTokenResult(
                False,
                None,
                f"토큰 발급 실패: HTTP {response.status_code}",
                "TOKEN_HTTP_ERROR",
                status_code=response.status_code,
                kis_base_url=norm_base,
                kis_http_path=KIS_OAUTH_TOKEN_HTTP_PATH,
                kis_tr_id=tr_id,
            )

        try:
            body: dict[str, Any] = response.json()
        except ValueError:
            return KISTokenResult(
                False,
                None,
                "토큰 발급 실패: 응답 JSON 파싱 오류",
                "TOKEN_JSON_ERROR",
                status_code=response.status_code,
                kis_base_url=norm_base,
                kis_http_path=KIS_OAUTH_TOKEN_HTTP_PATH,
                kis_tr_id=tr_id,
            )

        rt = str(body.get("rt_cd", "0"))
        if rt not in {"0", ""}:
            msg = str(body.get("msg1") or body.get("error_description") or "토큰 거절")
            return KISTokenResult(
                False,
                None,
                f"토큰 발급 실패: {msg}",
                "TOKEN_BUSINESS_ERROR",
                status_code=response.status_code,
                kis_base_url=norm_base,
                kis_http_path=KIS_OAUTH_TOKEN_HTTP_PATH,
                kis_tr_id=tr_id,
            )

        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            msg = str(body.get("msg1") or body.get("error_description") or "access_token 없음")
            return KISTokenResult(
                False,
                None,
                f"토큰 발급 실패: {msg}",
                "TOKEN_ISSUE_FAILED",
                status_code=response.status_code,
                kis_base_url=norm_base,
                kis_http_path=KIS_OAUTH_TOKEN_HTTP_PATH,
                kis_tr_id=tr_id,
            )

        logger.info("KIS access token issued (app_key_tail=%s)", mask_secret_tail(app_key))
        return KISTokenResult(
            True,
            token,
            "토큰 발급 성공",
            "OK",
            status_code=response.status_code,
            kis_base_url=norm_base,
            kis_http_path=KIS_OAUTH_TOKEN_HTTP_PATH,
            kis_tr_id=tr_id,
        )

    return KISTokenResult(
        False,
        None,
        f"토큰 발급 실패: {last_network!r}",
        "TOKEN_REQUEST_NETWORK_ERROR",
        kis_base_url=norm_base,
        kis_http_path=KIS_OAUTH_TOKEN_HTTP_PATH,
        kis_tr_id=tr_id,
    )
