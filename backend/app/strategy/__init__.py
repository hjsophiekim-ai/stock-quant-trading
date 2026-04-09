"""백엔드 실시간 종목 스크리너·랭킹.

`ranking` 등 하위 모듈만 필요할 때 무거운 screener(KIS 클라이언트)를 불러오지 않도록 지연 로딩합니다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["ScreeningSnapshot", "get_screener_engine"]

if TYPE_CHECKING:
    from backend.app.strategy.screener import ScreeningSnapshot as ScreeningSnapshot


def __getattr__(name: str) -> Any:
    if name == "ScreeningSnapshot":
        from backend.app.strategy.screener import ScreeningSnapshot

        return ScreeningSnapshot
    if name == "get_screener_engine":
        from backend.app.strategy.screener import get_screener_engine

        return get_screener_engine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
