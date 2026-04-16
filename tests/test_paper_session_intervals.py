from __future__ import annotations

import pytest

from app.config import Settings
from backend.app.engine.paper_session_controller import (
    PaperSessionController,
    paper_portfolio_sync_due,
    paper_positions_refresh_due,
)


def test_paper_field_defaults_reduce_kis_load() -> None:
    assert Settings.model_fields["paper_trading_symbols"].default == "005930,000660"
    assert Settings.model_fields["paper_kis_chart_lookback_days"].default == 60
    assert Settings.model_fields["paper_trading_interval_sec"].default == 600
    assert Settings.model_fields["paper_positions_refresh_interval_sec"].default == 900
    assert Settings.model_fields["paper_portfolio_sync_interval_sec"].default == 1800


def test_positions_not_due_every_tick_when_interval_large() -> None:
    """interval_sec=900 이면 직전 스냅 직후에는 추가 스냅이 필요 없음(매 틱 호출 아님)."""
    t0 = 10_000.0
    assert paper_positions_refresh_due(t0, 0.0, 900) is True
    assert paper_positions_refresh_due(t0 + 100.0, t0, 900) is False
    assert paper_positions_refresh_due(t0 + 900.0, t0, 900) is True


def test_portfolio_sync_not_due_every_tick() -> None:
    t0 = 5_000.0
    assert paper_portfolio_sync_due(t0, 0.0, 1800) is True
    assert paper_portfolio_sync_due(t0 + 60.0, t0, 1800) is False
    assert paper_portfolio_sync_due(t0 + 1800.0, t0, 1800) is True


def test_portfolio_sync_disabled_when_interval_zero() -> None:
    assert paper_portfolio_sync_due(100.0, 0.0, 0.0) is False


def test_positions_every_tick_when_interval_zero() -> None:
    assert paper_positions_refresh_due(100.0, 100.0, 0.0) is True


def test_paper_session_interval_uses_app_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_TRADING_INTERVAL_SEC", "333")
    from app.config import get_settings

    get_settings.cache_clear()
    c = PaperSessionController()
    assert c._interval_sec() == 333
    get_settings.cache_clear()


def test_paper_session_interval_final_betting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_LOOP_INTERVAL_SEC", "77")
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    c = PaperSessionController()
    c._strategy_id = "final_betting_v1"
    assert c._interval_sec() == 77
    get_settings.cache_clear()
