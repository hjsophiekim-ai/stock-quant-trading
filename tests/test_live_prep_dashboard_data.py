from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.brokers.base_broker import Fill, OpenOrder, PositionView
from backend.app.main import app


def test_live_prep_dashboard_data_returns_positions_orders_fills(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_prep_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_market_mode_store import LiveMarketModeStore

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        live_market_mode_store_json=str(tmp_path / "market_mode.json"),
    )
    monkeypatch.setattr(live_prep_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_prep_routes, "get_current_user_from_auth_header", lambda _h: SimpleNamespace(id="u1"))

    LiveMarketModeStore(cfg.live_market_mode_store_json).set("u1", market="domestic", manual_market_mode="aggressive")

    class FakeTok:
        ok = True
        access_token = "t"
        failure_code = None
        message = ""

    class FakeSvc:
        def get_plain_credentials(self, _uid):
            return ("k", "s", "acc", "01", "live")

        def ensure_cached_token_for_paper_start(self, _uid):
            return FakeTok()

        def _resolve_kis_api_base(self, _mode):
            return "https://openapi.koreainvestment.com:9443"

    monkeypatch.setattr(live_prep_routes, "get_broker_service", lambda: FakeSvc())
    monkeypatch.setattr(live_prep_routes, "build_kis_client_for_live_user", lambda **_kw: object())

    now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    class FakeBroker:
        def get_positions(self):
            return [PositionView(symbol="005930", quantity=10, average_price=70000.0)]

        def get_open_orders(self):
            return [
                OpenOrder(
                    order_id="o1",
                    symbol="005930",
                    side="buy",
                    quantity=10,
                    remaining_quantity=10,
                    price=70000.0,
                    created_at=now,
                )
            ]

        def get_fills(self):
            return [
                Fill(
                    fill_id="f1",
                    order_id="o0",
                    symbol="005930",
                    side="buy",
                    quantity=3,
                    fill_price=71000.0,
                    filled_at=now,
                )
            ]

    monkeypatch.setattr(live_prep_routes, "_build_live_broker_for_user", lambda **_kw: FakeBroker())

    c = TestClient(app)
    r = c.get("/api/live-prep/dashboard-data?execution_mode=live_shadow", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert j.get("manual_market_mode_override") == "aggressive"
    assert j.get("counts", {}).get("position_count") == 1
    assert j.get("counts", {}).get("open_order_count") == 1
    assert j.get("counts", {}).get("fill_count") == 1
    assert j.get("open_orders")[0]["created_at"].endswith("+00:00")
    assert j.get("recent_fills")[0]["filled_at"].endswith("+00:00")

