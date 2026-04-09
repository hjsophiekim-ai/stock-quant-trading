from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from backend.app.core.config import get_backend_settings

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

    data_dir = Path("backend_data")
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks["backend_data_writable"] = True
    except OSError:
        checks["backend_data_writable"] = False

    ok = all(checks.values())
    return {
        "status": "ready" if ok else "not_ready",
        "service": "backend-api",
        "checks": checks,
    }
