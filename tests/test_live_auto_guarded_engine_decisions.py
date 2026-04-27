from __future__ import annotations

from types import SimpleNamespace


def _cfg(tmp_path, **overrides):
    from backend.app.core.config import BackendSettings

    base = dict(
        trading_mode="live",
        execution_mode="live_auto_guarded",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto.json"),
        live_auto_guarded_equity_tracker_dir=str(tmp_path),
        live_market_mode_store_json=str(tmp_path / "mm.json"),
        live_trading=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
        live_auto_order=True,
        live_auto_buy_enabled=False,
        live_auto_sell_enabled=True,
        live_auto_require_market_open=False,
    )
    base.update(overrides)
    return BackendSettings(**base)


class _Tok:
    ok = True
    access_token = "t"
    failure_code = None
    message = ""


class _Svc:
    def get_plain_credentials(self, _uid):
        return ("k", "s", "acc", "01", "live")

    def ensure_cached_token_for_paper_start(self, _uid):
        return _Tok()

    def _resolve_kis_api_base(self, _mode):
        return "https://openapi.koreainvestment.com:9443"


class _Client:
    def __init__(self, price_by_symbol):
        self._px = dict(price_by_symbol)

    def get_quote(self, sym):
        return {"stck_prpr": self._px.get(sym, 0)}


def test_stop_loss_submits_sell(monkeypatch, tmp_path) -> None:
    from backend.app.engine import live_auto_guarded_engine as eng
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedStore, LiveAutoGuardedState

    cfg = _cfg(tmp_path, live_auto_buy_enabled=False)
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    monkeypatch.setattr(eng, "get_performance_signal", lambda *_a, **_k: SimpleNamespace(score_adjustment=0.0, buy_blocked=False, reason="ok", metrics={}))
    monkeypatch.setattr(eng, "build_kis_client_for_live_user", lambda **_kw: _Client({"AAA": 98.0}))

    class FakeBroker:
        def __init__(self):
            self.orders = []

        def get_positions(self):
            return [SimpleNamespace(symbol="AAA", quantity=10, average_price=100.0)]

        def get_open_orders(self):
            return []

        def get_fills(self):
            return []

        def get_cash(self):
            return 1_000_000.0

        def place_order(self, order):
            self.orders.append(order)
            return SimpleNamespace(order_id="o1", accepted=True, message="ok")

    fb = FakeBroker()
    monkeypatch.setattr(eng, "_build_live_broker", lambda **_kw: fb)
    monkeypatch.setattr(eng.EquityTracker, "pnl_snapshot", lambda *_a, **_k: (0.0, 0.0))

    out = eng.tick_live_auto_guarded(cfg=cfg, broker_service=_Svc(), user_id="u1", safety={"ok": True, "blockers": [], "blocker_details": []})
    assert out.get("ok") is True
    assert len(fb.orders) == 1
    assert fb.orders[0].side == "sell"
    assert fb.orders[0].symbol == "AAA"


def test_duplicate_open_order_blocks_buy(monkeypatch, tmp_path) -> None:
    from backend.app.engine import live_auto_guarded_engine as eng
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedStore, LiveAutoGuardedState

    cfg = _cfg(tmp_path, live_auto_buy_enabled=True, live_auto_sell_enabled=False)
    st = LiveAutoGuardedState(user_id="u1", enabled=True)
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(st)

    monkeypatch.setattr(eng, "get_performance_signal", lambda *_a, **_k: SimpleNamespace(score_adjustment=0.0, buy_blocked=False, reason="ok", metrics={}))
    monkeypatch.setattr(eng, "build_kis_client_for_live_user", lambda **_kw: _Client({}))

    class FakeBroker:
        def __init__(self):
            self.orders = []

        def get_positions(self):
            return []

        def get_open_orders(self):
            return [SimpleNamespace(symbol="BBB", side="buy", remaining_quantity=1)]

        def get_fills(self):
            return []

        def get_cash(self):
            return 5_000_000.0

        def place_order(self, order):
            self.orders.append(order)
            return SimpleNamespace(order_id="o1", accepted=True, message="ok")

    fb = FakeBroker()
    monkeypatch.setattr(eng, "_build_live_broker", lambda **_kw: fb)
    monkeypatch.setattr(eng.EquityTracker, "pnl_snapshot", lambda *_a, **_k: (0.0, 0.0))

    def fake_shadow(**_kw):
        return {"ok": True, "candidates": [{"symbol": "BBB", "side": "buy", "quantity": 2, "price": 50_000.0}], "market_mode": {"market_mode_active": "aggressive"}}

    import backend.app.engine.live_prep_engine as lpe

    monkeypatch.setattr(lpe, "generate_final_betting_shadow_candidates", fake_shadow)

    out = eng.tick_live_auto_guarded(cfg=cfg, broker_service=_Svc(), user_id="u1", safety={"ok": True, "blockers": [], "blocker_details": []})
    assert out.get("ok") is True
    assert out.get("submitted", {}).get("buys") == []
    assert fb.orders == []


def test_symbol_exposure_limit_blocks_buy(monkeypatch, tmp_path) -> None:
    from backend.app.engine import live_auto_guarded_engine as eng
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedStore, LiveAutoGuardedState

    cfg = _cfg(
        tmp_path,
        live_auto_buy_enabled=True,
        live_auto_sell_enabled=False,
        live_auto_max_symbol_exposure_krw=300_000.0,
        live_auto_max_order_krw=100_000.0,
    )
    st = LiveAutoGuardedState(user_id="u1", enabled=True)
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(st)

    monkeypatch.setattr(eng, "get_performance_signal", lambda *_a, **_k: SimpleNamespace(score_adjustment=0.0, buy_blocked=False, reason="ok", metrics={}))
    monkeypatch.setattr(eng, "build_kis_client_for_live_user", lambda **_kw: _Client({"CCC": 300_000.0}))

    class FakeBroker:
        def __init__(self):
            self.orders = []

        def get_positions(self):
            return [SimpleNamespace(symbol="CCC", quantity=1, average_price=300_000.0)]

        def get_open_orders(self):
            return []

        def get_fills(self):
            return []

        def get_cash(self):
            return 5_000_000.0

        def place_order(self, order):
            self.orders.append(order)
            return SimpleNamespace(order_id="o1", accepted=True, message="ok")

    fb = FakeBroker()
    monkeypatch.setattr(eng, "_build_live_broker", lambda **_kw: fb)
    monkeypatch.setattr(eng.EquityTracker, "pnl_snapshot", lambda *_a, **_k: (0.0, 0.0))

    def fake_shadow(**_kw):
        return {"ok": True, "candidates": [{"symbol": "CCC", "side": "buy", "quantity": 2, "price": 50_000.0}], "market_mode": {"market_mode_active": "aggressive"}}

    import backend.app.engine.live_prep_engine as lpe

    monkeypatch.setattr(lpe, "generate_final_betting_shadow_candidates", fake_shadow)

    out = eng.tick_live_auto_guarded(cfg=cfg, broker_service=_Svc(), user_id="u1", safety={"ok": True, "blockers": [], "blocker_details": []})
    assert out.get("ok") is True
    assert out.get("submitted", {}).get("buys") == []
    assert fb.orders == []


def test_daily_loss_limit_blocks_new_buys(monkeypatch, tmp_path) -> None:
    from backend.app.engine import live_auto_guarded_engine as eng
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedStore, LiveAutoGuardedState

    cfg = _cfg(
        tmp_path,
        live_auto_buy_enabled=True,
        live_auto_sell_enabled=False,
        live_auto_daily_loss_limit_pct=2.0,
        live_auto_require_market_open=False,
    )
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    monkeypatch.setattr(eng, "get_performance_signal", lambda *_a, **_k: SimpleNamespace(score_adjustment=0.0, buy_blocked=False, reason="ok", metrics={}))
    monkeypatch.setattr(eng, "build_kis_client_for_live_user", lambda **_kw: _Client({}))

    class FakeBroker:
        def __init__(self):
            self.orders = []

        def get_positions(self):
            return []

        def get_open_orders(self):
            return []

        def get_fills(self):
            return []

        def get_cash(self):
            return 5_000_000.0

        def place_order(self, order):
            self.orders.append(order)
            return SimpleNamespace(order_id="o1", accepted=True, message="ok")

    fb = FakeBroker()
    monkeypatch.setattr(eng, "_build_live_broker", lambda **_kw: fb)
    monkeypatch.setattr(eng.EquityTracker, "pnl_snapshot", lambda *_a, **_k: (-2.5, -1.0))

    out = eng.tick_live_auto_guarded(cfg=cfg, broker_service=_Svc(), user_id="u1", safety={"ok": True, "blockers": [], "blocker_details": []})
    assert out.get("ok") is True
    assert out.get("skipped") is True
    assert "daily_loss_limit_hit" in str(out.get("reason") or "")
    assert fb.orders == []


def test_safety_failure_does_not_call_place_order_but_returns_candidate_diagnostics(monkeypatch, tmp_path) -> None:
    from backend.app.engine import live_auto_guarded_engine as eng
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedStore, LiveAutoGuardedState

    cfg = _cfg(tmp_path, live_auto_buy_enabled=False, live_auto_sell_enabled=True)
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    monkeypatch.setattr(eng, "get_performance_signal", lambda *_a, **_k: SimpleNamespace(score_adjustment=0.0, buy_blocked=False, reason="ok", metrics={}))
    monkeypatch.setattr(eng, "build_kis_client_for_live_user", lambda **_kw: _Client({"AAA": 98.0}))

    class FakeBroker:
        def __init__(self):
            self.orders = []

        def get_positions(self):
            return [SimpleNamespace(symbol="AAA", quantity=10, average_price=100.0)]

        def get_open_orders(self):
            return []

        def get_fills(self):
            return []

        def get_cash(self):
            return 1_000_000.0

        def place_order(self, _order):
            raise AssertionError("place_order must not be called when safety.ok is false")

    fb = FakeBroker()
    monkeypatch.setattr(eng, "_build_live_broker", lambda **_kw: fb)
    monkeypatch.setattr(eng.EquityTracker, "pnl_snapshot", lambda *_a, **_k: (0.0, 0.0))

    def fake_shadow(**_kw):
        return {
            "ok": True,
            "candidate_count": 0,
            "candidates": [],
            "market_mode": {"market_mode_active": "neutral"},
            "shadow": {
                "fetch_summary": [{"symbol": "AAA", "bars_1m": 0, "fetch_error": "FETCH_SKIPPED safety_blocked"}],
                "last_diagnostics": [{"symbol": "AAA", "entered": False, "blocked_reason": "spread"}],
                "rejection_reasons_by_symbol": {"AAA": "spread"},
            },
        }

    import backend.app.engine.live_prep_engine as lpe

    monkeypatch.setattr(lpe, "generate_final_betting_shadow_candidates", fake_shadow)

    out = eng.tick_live_auto_guarded(cfg=cfg, broker_service=_Svc(), user_id="u1", safety={"ok": False, "blockers": ["PAPER_READINESS_FAILED"], "blocker_details": []})
    assert out.get("ok") is True
    assert out.get("blocked_before_order") is True
    assert out.get("safety_blockers") == ["PAPER_READINESS_FAILED"]
    assert out.get("candidate_count") == 0
    assert isinstance(out.get("fetch_summary"), list)
    assert len(out.get("last_diagnostics") or []) > 0
    assert out.get("rejection_reasons_by_symbol", {}).get("AAA") == "spread"

