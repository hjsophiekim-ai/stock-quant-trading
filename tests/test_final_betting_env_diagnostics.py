from __future__ import annotations

import pytest

from app.config import (
    clear_settings_cache,
    paper_final_betting_diagnostics,
    paper_final_betting_env_unset_in_process,
    paper_final_betting_enabled_fresh,
)


def test_final_betting_env_unset_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("PAPER_FINAL_BETTING_ENABLED", "FINAL_BETTING_ENABLED", "final_betting_enabled"):
        monkeypatch.delenv(k, raising=False)
    clear_settings_cache()
    assert paper_final_betting_env_unset_in_process() is True
    d = paper_final_betting_diagnostics()
    assert d["final_betting_env_unset_in_process"] is True
    assert d["final_betting_enabled_effective"] is False
    assert "Render" in str(d.get("final_betting_deploy_hint_ko") or "")
    assert paper_final_betting_enabled_fresh() is False


def test_final_betting_env_set_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_FINAL_BETTING_ENABLED", "true")
    clear_settings_cache()
    assert paper_final_betting_env_unset_in_process() is False
    d = paper_final_betting_diagnostics()
    assert d["final_betting_env_unset_in_process"] is False
    assert d["final_betting_enabled_effective"] is True
    assert paper_final_betting_enabled_fresh() is True
