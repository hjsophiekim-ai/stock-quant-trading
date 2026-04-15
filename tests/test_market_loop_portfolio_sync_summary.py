from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.app.engine.market_loop import BackendMarketLoop
from backend.app.portfolio.sync_engine import SyncRunResult


class _FakeJobs:
    def run_daily_cycle(self, **kwargs):
        return {"accepted_orders": 0, "rejected_orders": 0}


def _one_row_stock_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "005930",
                "date": pd.Timestamp("2026-01-01", tz="Asia/Seoul"),
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1.0,
            }
        ]
    )


def _one_row_index_df() -> pd.DataFrame:
    return pd.DataFrame({"date": [pd.Timestamp("2026-01-01", tz="Asia/Seoul")], "close": [1.0]})


def _fake_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        paper_trading_symbols="005930",
        paper_kis_chart_lookback_days=60,
        resolved_account_no="50000000",
        resolved_account_product_code="01",
    )


def test_intraday_tick_accepts_sync_run_result_without_snapshot() -> None:
    loop = BackendMarketLoop()
    client = MagicMock()
    client.inquire_nccs.return_value = {"output1": []}
    client.inquire_daily_ccld.return_value = {"output1": []}

    with (
        patch.object(loop, "_kis_client", return_value=client),
        patch.object(loop, "_build_jobs", return_value=_FakeJobs()),
        patch.object(loop, "_app_config", return_value=_fake_cfg()),
        patch("app.scheduler.kis_universe.build_kis_stock_universe", return_value=_one_row_stock_df()),
        patch("app.scheduler.kis_universe.build_kospi_index_series", return_value=_one_row_index_df()),
        patch("app.scheduler.kis_universe.build_mock_sp500_proxy_from_kospi", return_value=_one_row_index_df()),
        patch(
            "backend.app.engine.market_loop.run_portfolio_sync",
            return_value=SyncRunResult(ok=True, message="ok", snapshot=None),
        ),
        patch.object(loop._backend, "screener_auto_refresh_with_runtime", False),  # type: ignore[attr-defined]
    ):
        result = loop.run_intraday_tick()

    portfolio_sync = result.summary["portfolio_sync"]
    assert result.ok is True
    assert portfolio_sync["ok"] is True
    assert portfolio_sync["message"] == "ok"
    assert isinstance(portfolio_sync["warnings"], list)
    assert isinstance(portfolio_sync["updated_at_utc"], str)


def test_intraday_tick_exception_keeps_portfolio_sync_summary_shape() -> None:
    loop = BackendMarketLoop()
    with patch.object(loop, "_kis_client", side_effect=RuntimeError("forced_kis_failure")):
        result = loop.run_intraday_tick()

    portfolio_sync = result.summary["portfolio_sync"]
    assert result.ok is False
    assert result.error == "forced_kis_failure"
    assert set(portfolio_sync.keys()) == {"ok", "message", "updated_at_utc", "warnings"}
    assert portfolio_sync["ok"] is False
    assert portfolio_sync["message"] == "forced_kis_failure"
    assert isinstance(portfolio_sync["warnings"], list)
    assert isinstance(portfolio_sync["updated_at_utc"], str)


def test_afterhours_accepts_sync_run_result_without_snapshot(tmp_path) -> None:
    loop = BackendMarketLoop()
    client = MagicMock()
    client.get_balance.return_value = {"output1": []}
    client.inquire_nccs.return_value = {"output1": []}
    client.inquire_daily_ccld.return_value = {"output1": []}

    with (
        patch.object(loop, "_kis_client", return_value=client),
        patch.object(loop, "_app_config", return_value=_fake_cfg()),
        patch(
            "backend.app.engine.market_loop.run_portfolio_sync",
            return_value=SyncRunResult(ok=True, message="ok", snapshot=None),
        ),
    ):
        result = loop.run_afterhours(tmp_path)

    portfolio_sync = result.summary["portfolio_sync"]
    assert result.ok is True
    assert portfolio_sync["ok"] is True
    assert portfolio_sync["message"] == "ok"
    assert isinstance(portfolio_sync["warnings"], list)
    assert isinstance(portfolio_sync["updated_at_utc"], str)


def test_afterhours_exception_keeps_portfolio_sync_summary_shape(tmp_path) -> None:
    loop = BackendMarketLoop()
    with patch.object(loop, "_kis_client", side_effect=RuntimeError("forced_afterhours_failure")):
        result = loop.run_afterhours(tmp_path)

    portfolio_sync = result.summary["portfolio_sync"]
    assert result.ok is False
    assert result.error == "forced_afterhours_failure"
    assert set(portfolio_sync.keys()) == {"ok", "message", "updated_at_utc", "warnings"}
    assert portfolio_sync["ok"] is False
    assert portfolio_sync["message"] == "forced_afterhours_failure"
    assert isinstance(portfolio_sync["warnings"], list)
    assert isinstance(portfolio_sync["updated_at_utc"], str)
