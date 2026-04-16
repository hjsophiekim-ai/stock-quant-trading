"""KIS 해외 시세 EXCD ↔ 주문 OVRS_EXCG_CD — 공식 예제 필드 설명 기준."""

from __future__ import annotations

# price / inquire_time_itemchartprice 예제: EXCD = NAS, NYS, AMS (해외주식분봉조회 docstring)
# order / inquire_balance 예제: OVRS_EXCG_CD = NASD, NYSE, AMEX


def excd_for_price_chart(ovrs_excg_cd: str) -> str:
    m = (ovrs_excg_cd or "").strip().upper()
    if m == "NASD":
        return "NAS"
    if m == "NYSE":
        return "NYS"
    if m == "AMEX":
        return "AMS"
    return "NAS"


def prdt_type_cd_for_us_listing(ovrs_excg_cd: str) -> str | None:
    """search_info 의 prdt_type_cd (도움말: 512 나스닥 / 513 뉴욕 / 529 아멕스)."""
    m = (ovrs_excg_cd or "").strip().upper()
    if m == "NASD":
        return "512"
    if m == "NYSE":
        return "513"
    if m == "AMEX":
        return "529"
    return None
