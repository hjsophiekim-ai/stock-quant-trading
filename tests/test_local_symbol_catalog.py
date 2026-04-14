from backend.app.services.local_symbol_catalog import (
    catalog_size,
    search_by_name_kr,
    search_by_symbol_code,
    search_local_liquid_symbols,
)


def test_search_korean_name() -> None:
    r = search_by_name_kr(query="삼성", limit=5)
    assert len(r) >= 1
    assert any("삼성" in x["name_kr"] for x in r)


def test_search_symbol_prefix() -> None:
    r = search_by_symbol_code(query="00593", limit=5)
    assert any(x["symbol"] == "005930" for x in r)


def test_name_search_ignores_pure_symbol_style() -> None:
    """이름 검색은 숫자만 넣으면(코드) 빈 결과일 수 있음."""
    r = search_by_name_kr(query="005930", limit=5)
    assert isinstance(r, list)


def test_catalog_non_empty() -> None:
    assert catalog_size() >= 100
