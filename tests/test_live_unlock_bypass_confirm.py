from __future__ import annotations


def test_live_unlock_bypass_requires_confirm_in_production() -> None:
    from backend.app.core.config import BackendSettings
    from backend.app.risk.live_unlock_gate import evaluate_paper_readiness

    cfg = BackendSettings(
        app_env="production",
        live_unlock_enabled=True,
        live_unlock_bypass=True,
        live_unlock_bypass_confirm=False,
    )
    r = evaluate_paper_readiness(cfg)
    assert r.ok is False
    assert r.bypassed is False

    cfg2 = BackendSettings(
        app_env="production",
        live_unlock_enabled=True,
        live_unlock_bypass=True,
        live_unlock_bypass_confirm=True,
    )
    r2 = evaluate_paper_readiness(cfg2)
    assert r2.ok is True
    assert r2.bypassed is True

