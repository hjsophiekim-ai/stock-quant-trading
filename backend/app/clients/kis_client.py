from __future__ import annotations

from app.clients.kis_client import KISClient, KISClientError, KISLiveTradingLockedError
from app.config import get_settings as get_app_settings
from backend.app.core.config import BackendSettings, is_live_order_execution_configured, resolved_kis_api_base_url


def _kis_timing_from_app_settings():
    s = get_app_settings()
    return {
        "kis_min_request_interval_ms": s.kis_min_request_interval_ms,
        "kis_rate_limit_max_retries": s.kis_rate_limit_max_retries,
        "kis_rate_limit_backoff_base_sec": s.kis_rate_limit_backoff_base_sec,
        "kis_rate_limit_backoff_cap_sec": s.kis_rate_limit_backoff_cap_sec,
    }


def build_kis_client_for_backend(
    settings: BackendSettings,
    *,
    access_token: str,
    force_live_execution_unlock: bool | None = None,
) -> KISClient:
    """
    백엔드 환경변수로 base URL·실주문 잠금을 맞춘 KISClient.
    force_live_execution_unlock: 테스트 전용. None이면 설정에서 유도.
    """
    base = resolved_kis_api_base_url(settings)
    if force_live_execution_unlock is None:
        unlocked = is_live_order_execution_configured(settings)
    else:
        unlocked = bool(force_live_execution_unlock)
    t = _kis_timing_from_app_settings()
    return KISClient(
        base_url=base,
        token_provider=lambda: access_token,
        app_key=settings.kis_app_key,
        app_secret=settings.kis_app_secret,
        live_execution_unlocked=unlocked,
        **t,
    )


def build_kis_client_for_paper_user(
    *,
    base_url: str,
    access_token: str,
    app_key: str,
    app_secret: str,
) -> KISClient:
    """
    앱에 저장된 **모의투자** 자격으로 KISClient 생성.
    실전 호스트에서는 사용하지 않으며, 호출 전에 openapivts 여부를 검증해야 합니다.
    """
    base = base_url.rstrip("/")
    if "openapivts" not in base:
        raise ValueError("모의투자 호스트(openapivts)만 허용됩니다. live 경로와 혼합할 수 없습니다.")
    t = _kis_timing_from_app_settings()
    return KISClient(
        base_url=base,
        token_provider=lambda: access_token,
        app_key=app_key,
        app_secret=app_secret,
        live_execution_unlocked=False,
        **t,
    )


def build_kis_client_for_live_user(
    *,
    base_url: str,
    access_token: str,
    app_key: str,
    app_secret: str,
    live_execution_unlocked: bool,
) -> KISClient:
    base = base_url.rstrip("/")
    t = _kis_timing_from_app_settings()
    return KISClient(
        base_url=base,
        token_provider=lambda: access_token,
        app_key=app_key,
        app_secret=app_secret,
        live_execution_unlocked=bool(live_execution_unlocked),
        **t,
    )



__all__ = [
    "build_kis_client_for_backend",
    "build_kis_client_for_live_user",
    "build_kis_client_for_paper_user",
    "KISClient",
    "KISClientError",
    "KISLiveTradingLockedError",
]
