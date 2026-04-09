"""포트폴리오 동기화·손익 집계 (KIS 모의 계좌 기준).

하위 모듈(예: performance_math)만 필요할 때 무거운 sync_engine 을 불러오지 않도록
엔트리 포인트는 지연 로딩합니다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["PortfolioSyncEngine", "run_portfolio_sync"]

if TYPE_CHECKING:
    from backend.app.portfolio.sync_engine import PortfolioSyncEngine as PortfolioSyncEngine


def __getattr__(name: str) -> Any:
    if name == "PortfolioSyncEngine":
        from backend.app.portfolio.sync_engine import PortfolioSyncEngine

        return PortfolioSyncEngine
    if name == "run_portfolio_sync":
        from backend.app.portfolio.sync_engine import run_portfolio_sync

        return run_portfolio_sync
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
