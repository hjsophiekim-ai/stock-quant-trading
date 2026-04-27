from __future__ import annotations

from unittest.mock import MagicMock

from app.clients.kis_client import KISClient


def test_live_prep_build_live_broker_for_user_sets_live_flags(monkeypatch) -> None:
    from backend.app.api import live_prep_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        live_trading=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
    )
    client = MagicMock(spec=KISClient)
    b = live_prep_routes._build_live_broker_for_user(cfg=cfg, client=client, account_no="1234", product_code="01", read_only=False)
    assert b.trading_mode == "live"
    assert b.live_trading_enabled is True
    assert b.live_trading_confirm is True
    assert b.live_trading_extra_confirm is True
    assert b.startup_safety_passed is True


def test_generate_final_betting_shadow_candidates_returns_without_tok_nameerror(monkeypatch, tmp_path) -> None:
    import pandas as pd
    from types import SimpleNamespace

    from backend.app.engine import live_prep_engine as mod

    class DummyBroker:
        def get_positions(self):
            return []

        def get_cash(self):
            return 0.0

    class DummyCfg:
        paper_intraday_chart_cache_ttl_sec = 10.0
        paper_intraday_chart_min_interval_sec = 0.2
        paper_kis_chart_lookback_days = 60

        def resolved_final_betting_symbol_list(self):
            return ["005930", "000660"]

    class DummySnap:
        state = "regular"
        fetch_allowed = True
        fetch_block_reason = ""
        regular_session_kst = {}

    class DummyStateStore:
        def __init__(self, *_a, **_kw):
            pass

        def load(self):
            return {}

        def save(self, _st):
            return None

    class DummyStrategy:
        def __init__(self):
            self.last_diagnostics = [{"symbol": "005930", "entered": False, "blocked_reason": "spread"}]
            self.last_intraday_signal_breakdown = {"entry_window": "open"}
            self.intraday_state = {}
            self.quote_by_symbol = {}

        def generate_orders(self, _ctx):
            return []

    monkeypatch.setattr(mod, "_build_live_client_and_broker", lambda **_kw: (object(), DummyBroker(), {"ok": True}, ""))
    monkeypatch.setattr(mod, "get_app_settings", lambda: DummyCfg())
    monkeypatch.setattr(mod, "analyze_krx_intraday_session", lambda **_kw: DummySnap())
    monkeypatch.setattr(
        mod,
        "build_intraday_universe_1m",
        lambda *_a, **_kw: (pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"]), [{"symbol": "005930", "bars_1m": 0, "fetch_error": ""}]),
    )
    monkeypatch.setattr(mod, "build_kospi_index_series", lambda *_a, **_kw: pd.DataFrame(columns=["date", "close"]))
    monkeypatch.setattr(mod, "build_mock_sp500_proxy_from_kospi", lambda *_a, **_kw: pd.DataFrame(columns=["date", "close"]))
    monkeypatch.setattr(mod, "build_mock_volatility_series", lambda *_a, **_kw: pd.DataFrame(columns=["date", "close"]))
    monkeypatch.setattr(mod, "fetch_quotes_throttled", lambda *_a, **_kw: {})
    monkeypatch.setattr(mod, "IntradayPaperStateStore", DummyStateStore)
    monkeypatch.setattr(mod, "FinalBettingV1Strategy", DummyStrategy)
    monkeypatch.setattr(mod, "attach_market_mode_to_strategy", lambda *_a, **_kw: {"market_mode_active": "neutral"})

    out = mod.generate_final_betting_shadow_candidates(
        broker_service=object(),
        backend_settings=SimpleNamespace(backend_data_dir=str(tmp_path)),
        user_id="u1",
        limit=5,
    )
    assert "candidate_count" in out
    assert "candidates" in out
    assert "shadow" in out


def test_generate_final_betting_shadow_candidates_ok_true_even_when_zero_candidates_and_has_diagnostics(monkeypatch, tmp_path) -> None:
    import pandas as pd
    from types import SimpleNamespace

    from backend.app.engine import live_prep_engine as mod

    class DummyBroker:
        def get_positions(self):
            return []

        def get_cash(self):
            return 0.0

    class DummyCfg:
        paper_intraday_chart_cache_ttl_sec = 10.0
        paper_intraday_chart_min_interval_sec = 0.2
        paper_kis_chart_lookback_days = 60

        def resolved_final_betting_symbol_list(self):
            return ["005930", "000660"]

    class DummySnap:
        state = "regular"
        fetch_allowed = True
        fetch_block_reason = ""
        regular_session_kst = {}

    class DummyStateStore:
        def __init__(self, *_a, **_kw):
            pass

        def load(self):
            return {}

        def save(self, _st):
            return None

    class DummyStrategy:
        def __init__(self):
            self.last_diagnostics = [
                {"symbol": "005930", "entered": False, "blocked_reason": "min_trade_value"},
                {"symbol": "000660", "entered": False, "blocked_reason": "signals_weak"},
            ]
            self.last_intraday_signal_breakdown = {"entry_window": "open"}
            self.intraday_state = {}
            self.quote_by_symbol = {}

        def generate_orders(self, _ctx):
            return []

    monkeypatch.setattr(mod, "_build_live_client_and_broker", lambda **_kw: (object(), DummyBroker(), {"ok": True, "hit": True}, ""))
    monkeypatch.setattr(mod, "get_app_settings", lambda: DummyCfg())
    monkeypatch.setattr(mod, "analyze_krx_intraday_session", lambda **_kw: DummySnap())
    monkeypatch.setattr(
        mod,
        "build_intraday_universe_1m",
        lambda *_a, **_kw: (pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"]), [{"symbol": "005930", "bars_1m": 120, "fetch_error": ""}]),
    )
    monkeypatch.setattr(mod, "build_kospi_index_series", lambda *_a, **_kw: pd.DataFrame(columns=["date", "close"]))
    monkeypatch.setattr(mod, "build_mock_sp500_proxy_from_kospi", lambda *_a, **_kw: pd.DataFrame(columns=["date", "close"]))
    monkeypatch.setattr(mod, "build_mock_volatility_series", lambda *_a, **_kw: pd.DataFrame(columns=["date", "close"]))
    monkeypatch.setattr(mod, "fetch_quotes_throttled", lambda *_a, **_kw: {})
    monkeypatch.setattr(mod, "IntradayPaperStateStore", DummyStateStore)
    monkeypatch.setattr(mod, "FinalBettingV1Strategy", DummyStrategy)
    monkeypatch.setattr(mod, "attach_market_mode_to_strategy", lambda *_a, **_kw: {"market_mode_active": "neutral"})

    out = mod.generate_final_betting_shadow_candidates(
        broker_service=object(),
        backend_settings=SimpleNamespace(backend_data_dir=str(tmp_path)),
        user_id="u1",
        limit=5,
    )
    assert out["ok"] is True
    assert out["candidate_count"] == 0
    assert isinstance(out["candidates"], list)
    assert "fetch_summary" in out["shadow"]
    assert "last_diagnostics" in out["shadow"]
    assert len(out["shadow"]["last_diagnostics"]) > 0

