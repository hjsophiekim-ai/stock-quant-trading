from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.config import get_backend_settings
from backend.app.core.storage_paths import directory_is_writable, get_resolved_storage_paths

router = APIRouter(tags=["health"])


@router.api_route("/health", methods=["GET", "HEAD"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "backend-api"}


@router.api_route("/ready", methods=["GET", "HEAD"])
def ready() -> dict[str, object]:
    """
    운영 배포용 readiness 힌트.
    - 핵심 설정(APP_SECRET_KEY) 존재
    - backend_data 디렉터리 쓰기 가능
    """
    cfg = get_backend_settings()
    checks: dict[str, bool] = {}

    checks["app_secret_configured"] = bool((cfg.app_secret_key or "").strip())

    paths = get_resolved_storage_paths()
    checks["backend_data_writable"] = directory_is_writable(paths.backend_data_dir)

    ok = all(checks.values())
    return {
        "status": "ready" if ok else "not_ready",
        "service": "backend-api",
        "checks": checks,
    }
