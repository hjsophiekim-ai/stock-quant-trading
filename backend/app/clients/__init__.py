"""KIS REST 클라이언트 팩토리 (백엔드 설정 기준)."""

from backend.app.clients.kis_client import build_kis_client_for_backend

__all__ = ["build_kis_client_for_backend"]
