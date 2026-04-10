"""배포 반영 여부 확인용 버전 정보 (민감값 없음)."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.version_info import get_backend_version_payload

router = APIRouter(prefix="/version", tags=["version"])


# FastAPI app.version 과 맞출 것 (backend/app/main.py)
_BACKEND_APP_VERSION = "0.1.0"


@router.get("")
def get_version() -> dict[str, str]:
    return get_backend_version_payload(app_version=_BACKEND_APP_VERSION)
