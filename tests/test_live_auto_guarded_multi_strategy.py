from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo


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
        live_auto_buy_enabled=True,
        live_auto_sell_enabled=False,
        live_auto_require_market_open=False,
        live_auto_max_order_krw=100_000.0,
        live_auto_min_cash_buffer_krw=100_000.0,
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
    def __init__(self, price_by_symbol=None):
        self._px = dict(price_by_symbol or {})

    def get_quote(self, sym):
        return {"stck_prpr": self._px.get(sym, 50_000.0)}


class _Broker:
    def __init__(self, *, cash=5_000_000.0):
        self._cash = float(cash)
        self.orders = []

    def get_positions(self):
        return []

    def get_open_orders(self):
        return []

    def get_fills(self):
        return []

    def get_cash(self):
        return float(self._cash)

    def place_order(self, order):
        self.orders.append(order)
        return SimpleNamespace(order_id="o1", accepted=True, message="ok")


def _kst(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("Asia/Seoul"))


def test_live_auto_strategy_final_betting_keeps_old_path(monkeypatch, tmp_path) -> None:
    from backend.app.engine import live_auto_guarded_engine as eng
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedState, LiveAutoGuardedStore
    import backend.app.engine.live_prep_engine as lpe

    cfg = _cfg(tmp_path, live_auto_strategy="final_betting_v1")
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    monkeypatch.setattr(eng, "build_kis_client_for_live_user", lambda **_kw: _Client({"AAA": 100_000.0}))
    fb = _Broker()
    monkeypatch.setattr(eng, "_build_live_broker", lambda **_kw: fb)
    monkeypatch.setattr(eng.EquityTracker, "pnl_snapshot", lambda *_a, **_k: (0.0, 0.0))
    monkeypatch.setattr(eng, "kst_now", lambda: _kst(2026, 4, 28, 14, 40))

    called = {"n": 0}

    def fake_fb(**_kw):
        called["n"] += 1
        return {
            "ok": True,
            "candidate_count": 1,
            "candidates": [
                {"candidate_id": "c1", "symbol": "AAA", "side": "buy", "quantity": 1, "price": 100_000.0, "strategy_id": "final_betting_v1", "score": 90.0, "rationale": "x"}
            ],
            "market_mode": {"market_mode_active": "neutral"},
            "shadow": {"fetch_summary": [{"symbol": "AAA"}], "last_diagnostics": [], "rejection_reasons_by_symbol": {}},
        }

    monkeypatch.setattr(lpe, "generate_final_betting_shadow_candidates", fake_fb)

    out = eng.tick_live_auto_guarded(cfg=cfg, broker_service=_Svc(), user_id="u1", safety={"ok": True, "blockers": [], "blocker_details": []})
    assert out.get("ok") is True
    assert called["n"] == 1
    assert out.get("candidate_count") >= 1


def test_live_auto_strategy_scalp_calls_intraday_path(monkeypatch, tmp_path) -> None:
    from backend.app.engine import live_auto_guarded_engine as eng
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedState, LiveAutoGuardedStore
    import backend.app.engine.live_prep_engine as lpe

    cfg = _cfg(tmp_path, live_auto_strategy="scalp_rsi_flag_hf_v1")
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    monkeypatch.setattr(eng, "build_kis_client_for_live_user", lambda **_kw: _Client({"AAA": 50_000.0}))
    fb = _Broker()
    monkeypatch.setattr(eng, "_build_live_broker", lambda **_kw: fb)
    monkeypatch.setattr(eng.EquityTracker, "pnl_snapshot", lambda *_a, **_k: (0.0, 0.0))
    monkeypatch.setattr(eng, "kst_now", lambda: _kst(2026, 4, 28, 10, 5))

    called = {"sid": None}

    def fake_intraday(**kw):
        called["sid"] = kw.get("strategy_id")
        return {
            "ok": True,
            "strategy_id": kw.get("strategy_id"),
            "generated_orders": [{"symbol": "AAA", "side": "buy", "quantity": 1, "price": None, "strategy_id": kw.get("strategy_id"), "signal_reason": "sig"}],
            "last_diagnostics": [{"symbol": "AAA", "entered": True, "momentum_path_hits": 3}],
            "market_mode": {"market_mode_active": "neutral"},
            "fetch_summary": [],
        }

    monkeypatch.setattr(lpe, "generate_intraday_shadow_report", fake_intraday)

    out = eng.tick_live_auto_guarded(cfg=cfg, broker_service=_Svc(), user_id="u1", safety={"ok": True, "blockers": [], "blocker_details": []})
    assert out.get("ok") is True
    assert called["sid"] == "scalp_rsi_flag_hf_v1"
    assert out.get("candidate_count") >= 1


def test_multi_strategy_merges_candidates_and_skips_final_betting_outside_window(monkeypatch, tmp_path) -> None:
    from backend.app.engine import live_auto_guarded_engine as eng
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedState, LiveAutoGuardedStore
    import backend.app.engine.live_prep_engine as lpe

    cfg = _cfg(tmp_path, live_auto_strategy="multi", live_auto_strategies="final_betting_v1,scalp_rsi_flag_hf_v1")
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    monkeypatch.setattr(eng, "build_kis_client_for_live_user", lambda **_kw: _Client({"AAA": 50_000.0}))
    fb = _Broker()
    monkeypatch.setattr(eng, "_build_live_broker", lambda **_kw: fb)
    monkeypatch.setattr(eng.EquityTracker, "pnl_snapshot", lambda *_a, **_k: (0.0, 0.0))
    monkeypatch.setattr(eng, "kst_now", lambda: _kst(2026, 4, 28, 10, 0))

    def fake_fb(**_kw):
        raise AssertionError("final_betting should be skipped outside entry window")

    monkeypatch.setattr(lpe, "generate_final_betting_shadow_candidates", fake_fb)

    def fake_intraday(**_kw):
        return {
            "ok": True,
            "strategy_id": "scalp_rsi_flag_hf_v1",
            "generated_orders": [{"symbol": "AAA", "side": "buy", "quantity": 1, "price": None, "strategy_id": "scalp_rsi_flag_hf_v1", "signal_reason": "sig"}],
            "last_diagnostics": [{"symbol": "AAA", "entered": True, "momentum_path_hits": 3}],
            "market_mode": {"market_mode_active": "neutral"},
            "fetch_summary": [],
        }

    monkeypatch.setattr(lpe, "generate_intraday_shadow_report", fake_intraday)

    out = eng.tick_live_auto_guarded(cfg=cfg, broker_service=_Svc(), user_id="u1", safety={"ok": True, "blockers": [], "blocker_details": []})
    assert out.get("ok") is True
    ev = out.get("evaluation") or {}
    rows = ev.get("strategies") or []
    by = {r.get("strategy_id"): r for r in rows if isinstance(r, dict)}
    assert by["final_betting_v1"]["evaluated"] is False
    assert by["scalp_rsi_flag_hf_v1"]["evaluated"] is True
    assert out.get("candidate_count") >= 1


def test_safety_false_still_evaluates_but_does_not_submit(monkeypatch, tmp_path) -> None:
    from backend.app.engine import live_auto_guarded_engine as eng
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedState, LiveAutoGuardedStore
    import backend.app.engine.live_prep_engine as lpe

    cfg = _cfg(tmp_path, live_auto_strategy="scalp_rsi_flag_hf_v1")
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    monkeypatch.setattr(eng, "build_kis_client_for_live_user", lambda **_kw: _Client({"AAA": 50_000.0}))
    fb = _Broker()
    monkeypatch.setattr(eng, "_build_live_broker", lambda **_kw: fb)
    monkeypatch.setattr(eng.EquityTracker, "pnl_snapshot", lambda *_a, **_k: (0.0, 0.0))
    monkeypatch.setattr(eng, "kst_now", lambda: _kst(2026, 4, 28, 10, 0))

    def fake_intraday(**_kw):
        return {
            "ok": True,
            "strategy_id": "scalp_rsi_flag_hf_v1",
            "generated_orders": [{"symbol": "AAA", "side": "buy", "quantity": 1, "price": None, "strategy_id": "scalp_rsi_flag_hf_v1", "signal_reason": "sig"}],
            "last_diagnostics": [{"symbol": "AAA", "entered": True, "momentum_path_hits": 3}],
            "market_mode": {"market_mode_active": "neutral"},
            "fetch_summary": [],
        }

    monkeypatch.setattr(lpe, "generate_intraday_shadow_report", fake_intraday)

    out = eng.tick_live_auto_guarded(cfg=cfg, broker_service=_Svc(), user_id="u1", safety={"ok": False, "blockers": ["x"], "blocker_details": []})
    assert out.get("ok") is True
    assert out.get("blocked_before_order") is True
    assert out.get("candidate_count") >= 1
    assert fb.orders == []


def test_safety_true_submits_when_candidate_exists(monkeypatch, tmp_path) -> None:
    from backend.app.engine import live_auto_guarded_engine as eng
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedState, LiveAutoGuardedStore
    import backend.app.engine.live_prep_engine as lpe

    cfg = _cfg(tmp_path, live_auto_strategy="scalp_rsi_flag_hf_v1")
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    monkeypatch.setattr(eng, "build_kis_client_for_live_user", lambda **_kw: _Client({"AAA": 50_000.0}))
    fb = _Broker()
    monkeypatch.setattr(eng, "_build_live_broker", lambda **_kw: fb)
    monkeypatch.setattr(eng.EquityTracker, "pnl_snapshot", lambda *_a, **_k: (0.0, 0.0))
    monkeypatch.setattr(eng, "kst_now", lambda: _kst(2026, 4, 28, 10, 0))

    def fake_intraday(**_kw):
        return {
            "ok": True,
            "strategy_id": "scalp_rsi_flag_hf_v1",
            "generated_orders": [{"symbol": "AAA", "side": "buy", "quantity": 1, "price": None, "strategy_id": "scalp_rsi_flag_hf_v1", "signal_reason": "sig"}],
            "last_diagnostics": [{"symbol": "AAA", "entered": True, "momentum_path_hits": 4}],
            "market_mode": {"market_mode_active": "neutral"},
            "fetch_summary": [],
        }

    monkeypatch.setattr(lpe, "generate_intraday_shadow_report", fake_intraday)

    out = eng.tick_live_auto_guarded(cfg=cfg, broker_service=_Svc(), user_id="u1", safety={"ok": True, "blockers": [], "blocker_details": []})
    assert out.get("ok") is True
    assert len(fb.orders) == 1
    assert fb.orders[0].side == "buy"
    assert fb.orders[0].symbol == "AAA"

