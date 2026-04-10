from __future__ import annotations

import pytest


def test_paper_universe_ttl_accepts_short_env_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_UNIVERSE_CACHE_TTL_SEC", "222")
    monkeypatch.setenv("PAPER_KOSPI_CACHE_TTL_SEC", "333")
    from app.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.paper_kis_universe_cache_ttl_sec == 222
    assert s.paper_kis_kospi_cache_ttl_sec == 333
    get_settings.cache_clear()


def test_paper_kis_prefixed_ttl_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_KIS_UNIVERSE_CACHE_TTL_SEC", "111")
    monkeypatch.setenv("PAPER_KIS_KOSPI_CACHE_TTL_SEC", "444")
    from app.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.paper_kis_universe_cache_ttl_sec == 111
    assert s.paper_kis_kospi_cache_ttl_sec == 444
    get_settings.cache_clear()
