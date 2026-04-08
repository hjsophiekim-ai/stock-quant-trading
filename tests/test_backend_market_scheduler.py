from datetime import datetime
from zoneinfo import ZoneInfo

from backend.app.engine.scheduler import MarketPhase, classify_market_phase

KST = ZoneInfo("Asia/Seoul")


def test_weekday_session_is_session() -> None:
    # 2026-04-08 is Wednesday
    dt = datetime(2026, 4, 8, 10, 30, tzinfo=KST)
    assert classify_market_phase(dt) == MarketPhase.SESSION


def test_weekday_premarket() -> None:
    dt = datetime(2026, 4, 8, 8, 30, tzinfo=KST)
    assert classify_market_phase(dt) == MarketPhase.PREMARKET


def test_weekday_afterhours() -> None:
    dt = datetime(2026, 4, 8, 16, 0, tzinfo=KST)
    assert classify_market_phase(dt) == MarketPhase.AFTERHOURS


def test_saturday_closed() -> None:
    dt = datetime(2026, 4, 11, 10, 0, tzinfo=KST)
    assert classify_market_phase(dt) == MarketPhase.CLOSED
