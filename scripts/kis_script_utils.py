"""
KIS 점검 스크립트 공통: 경로 설정, 설정 로드, 토큰, base URL.
민감정보는 로그에 남기지 않습니다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.clients.kis_client import KISClient
    from app.config import Settings

_REPO_ROOT = Path(__file__).resolve().parents[1]


def ensure_repo_on_path() -> None:
    r = str(_REPO_ROOT)
    if r not in sys.path:
        sys.path.insert(0, r)


def load_app_settings() -> "Settings":
    ensure_repo_on_path()
    from app.config import get_settings

    return get_settings()


def resolved_kis_base_url(cfg: "Settings") -> str:
    from app.clients.kis_contract import resolve_trading_api_base_url

    return resolve_trading_api_base_url(
        trading_mode=cfg.trading_mode,
        kis_mock_base_url=cfg.kis_mock_base_url,
        kis_live_base_url=cfg.kis_base_url,
    )


def issue_token_or_exit(cfg: "Settings", *, base_url: str, logger) -> str:
    from backend.app.auth.kis_auth import issue_access_token, validate_kis_inputs

    issues = validate_kis_inputs(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        account_no="",
        account_product_code="",
        base_url=base_url,
        require_account=False,
    )
    if issues:
        for msg in issues:
            logger.error(msg)
        raise SystemExit(1)

    tr = issue_access_token(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        base_url=base_url,
        timeout_sec=10,
    )
    if not tr.ok or not tr.access_token:
        logger.error("%s (code=%s)", tr.message, tr.error_code)
        raise SystemExit(1)
    return tr.access_token


def build_kis_client(cfg: "Settings", *, base_url: str, access_token: str) -> "KISClient":
    from app.clients.kis_client import KISClient

    return KISClient(
        base_url=base_url,
        timeout_sec=12,
        max_retries=2,
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        token_provider=lambda: access_token,
        live_execution_unlocked=False,
    )
