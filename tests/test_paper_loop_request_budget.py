from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from app.config import Settings
from backend.app.engine.user_paper_loop import UserPaperTradingLoop


def test_universe_kospi_cache_reduces_rebuilds(monkeypatch) -> None:
    """동일 시그니처·TTL 내 두 번째 틱은 universe/kospi 빌드 호출이 증가하지 않음."""
    monkeypatch.setenv("PAPER_KIS_UNIVERSE_CACHE_TTL_SEC", "600")
    monkeypatch.setenv("PAPER_KIS_KOSPI_CACHE_TTL_SEC", "600")
    monkeypatch.setenv("PAPER_TRADING_SYMBOLS", "005930")
    monkeypatch.setenv("PAPER_KIS_CHART_LOOKBACK_DAYS", "60")

    from app.config import get_settings

    get_settings.cache_clear()

    calls = {"u": 0, "k": 0}

    def count_u(client, symbols, *, lookback_calendar_days: int = 180, logger=None):
        calls["u"] += 1
        return pd.DataFrame(
            [{"symbol": "005930", "date": pd.Timestamp("2026-01-01", tz="Asia/Seoul"), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
        )

    def count_k(client, *, lookback_calendar_days: int = 180, logger=None):
        calls["k"] += 1
        return pd.DataFrame({"date": [pd.Timestamp("2026-01-01", tz="Asia/Seoul")], "close": [1.0]})

    class FakeJobs:
        def run_daily_cycle(self, **kwargs):
            return {"accepted_orders": 0, "rejected_orders": 0, "equity": 1.0, "daily_return_pct": 0.0, "cumulative_return_pct": 0.0}

    loop = UserPaperTradingLoop(
        app_key="k",
        app_secret="s",
        account_no="50000000",
        product_code="01",
        api_base="https://openapivts.koreainvestment.com:29443",
        strategy_id="swing_v1",
        user_tag="utest",
        initial_access_token="tok",
    )

    with (
        patch.object(loop, "_kis_client", return_value=MagicMock()),
        patch.object(loop, "_build_jobs", return_value=FakeJobs()),
        patch("backend.app.engine.user_paper_loop.build_kis_stock_universe", side_effect=count_u),
        patch("backend.app.engine.user_paper_loop.build_kospi_index_series", side_effect=count_k),
        patch.object(loop._backend, "screener_auto_refresh_with_runtime", False),  # type: ignore[attr-defined]
    ):
        r1 = loop.run_intraday_tick()
        r2 = loop.run_intraday_tick()
    assert r1.get("ok") is True
    assert r2.get("ok") is True
    assert calls["u"] == 1, "universe should be cached on second tick"
    assert calls["k"] == 1, "kospi should be cached on second tick"


def test_tick_returns_cache_hit_flags(monkeypatch) -> None:
    monkeypatch.setenv("PAPER_KIS_UNIVERSE_CACHE_TTL_SEC", "600")
    monkeypatch.setenv("PAPER_KIS_KOSPI_CACHE_TTL_SEC", "600")
    monkeypatch.setenv("PAPER_TRADING_SYMBOLS", "005930,000660")
    monkeypatch.setenv("PAPER_KIS_CHART_LOOKBACK_DAYS", "60")
    from app.config import get_settings

    get_settings.cache_clear()

    def one_row_u(client, symbols, *, lookback_calendar_days: int = 180, logger=None):
        return pd.DataFrame(
            [
                {
                    "symbol": symbols[0],
                    "date": pd.Timestamp("2026-01-01", tz="Asia/Seoul"),
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 1,
                    "volume": 1,
                }
            ]
        )

    def one_row_k(client, *, lookback_calendar_days: int = 180, logger=None):
        return pd.DataFrame({"date": [pd.Timestamp("2026-01-01", tz="Asia/Seoul")], "close": [1.0]})

    class FakeJobs:
        def run_daily_cycle(self, **kwargs):
            return {"accepted_orders": 0, "rejected_orders": 0, "equity": 1.0, "daily_return_pct": 0.0, "cumulative_return_pct": 0.0}

    loop = UserPaperTradingLoop(
        app_key="k",
        app_secret="s",
        account_no="50000000",
        product_code="01",
        api_base="https://openapivts.koreainvestment.com:29443",
        strategy_id="swing_v1",
        user_tag="utest",
        initial_access_token="tok",
    )

    with (
        patch.object(loop, "_kis_client", return_value=MagicMock()),
        patch.object(loop, "_build_jobs", return_value=FakeJobs()),
        patch("backend.app.engine.user_paper_loop.build_kis_stock_universe", side_effect=one_row_u),
        patch("backend.app.engine.user_paper_loop.build_kospi_index_series", side_effect=one_row_k),
        patch.object(loop._backend, "screener_auto_refresh_with_runtime", False),  # type: ignore[attr-defined]
    ):
        a = loop.run_intraday_tick()
        b = loop.run_intraday_tick()
    get_settings.cache_clear()
    assert a.get("universe_cache_hit") is False
    assert a.get("kospi_cache_hit") is False
    assert b.get("universe_cache_hit") is True
    assert b.get("kospi_cache_hit") is True
    assert b.get("request_budget_mode") == "paper_conserve"


def test_default_symbol_count_is_two() -> None:
    raw = Settings.model_fields["paper_trading_symbols"].default
    syms = [s.strip() for s in str(raw).split(",") if s.strip()]
    assert len(syms) == 2
