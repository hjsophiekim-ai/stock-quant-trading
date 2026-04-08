"""
한국 장(KST) 세션 구간 분류.

장 운영일·공휴일 캘린더는 포함하지 않으며, 평일 시간대만 구분합니다.
세부 시각은 환경변수로 조정 가능합니다.
"""

from __future__ import annotations

from datetime import datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")


class MarketPhase(StrEnum):
    CLOSED = "closed"
    PREMARKET = "premarket"
    SESSION = "session"
    AFTERHOURS = "afterhours"


def now_kst() -> datetime:
    return datetime.now(_KST)


def classify_market_phase(
    when: datetime | None = None,
    *,
    premarket_start: time = time(8, 0),
    session_open: time = time(9, 0),
    session_close: time = time(15, 30),
    afterhours_end: time = time(20, 0),
) -> MarketPhase:
    """
    평일(월~금) 기준 시간대 분류.
    - premarket: [premarket_start, session_open)
    - session: [session_open, session_close)
    - afterhours: [session_close, afterhours_end)
    - 그 외: closed
    """
    dt = when.astimezone(_KST) if when else now_kst()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_KST)
    else:
        dt = dt.astimezone(_KST)

    if dt.weekday() >= 5:
        return MarketPhase.CLOSED

    t = dt.time()
    if t < premarket_start or t >= afterhours_end:
        return MarketPhase.CLOSED
    if premarket_start <= t < session_open:
        return MarketPhase.PREMARKET
    if session_open <= t < session_close:
        return MarketPhase.SESSION
    return MarketPhase.AFTERHOURS
