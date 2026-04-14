"""
KIS Open API: 엔드포인트 경로, TR_ID, 호스트(모의/실전) 분기.

공식 문서의 TR 변경에 대비해 상수는 이 모듈에만 모읍니다.
"""

from __future__ import annotations

from dataclasses import dataclass


MOCK_HOST_PREFIX = "https://openapivts"


def is_paper_host(base_url: str) -> bool:
    u = (base_url or "").strip().rstrip("/").lower()
    return u.startswith(MOCK_HOST_PREFIX.lower())


def resolve_trading_api_base_url(
    *,
    trading_mode: str,
    kis_mock_base_url: str,
    kis_live_base_url: str,
) -> str:
    """TRADING_MODE=paper 이면 모의 URL, 그 외에는 실전 URL."""
    mode = (trading_mode or "paper").strip().lower()
    if mode == "paper":
        return (kis_mock_base_url or kis_live_base_url).rstrip("/")
    return (kis_live_base_url or kis_mock_base_url).rstrip("/")


@dataclass(frozen=True)
class DomesticStockPaths:
    """국내주식 REST path (v1)."""

    balance: str = "/uapi/domestic-stock/v1/trading/inquire-balance"
    quote: str = "/uapi/domestic-stock/v1/quotations/inquire-price"
    order_cash: str = "/uapi/domestic-stock/v1/trading/order-cash"
    order_cancel: str = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
    hashkey: str = "/uapi/hashkey"
    daily_itemchart: str = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    # 당일 분봉 (시간별 OHLC) — 공식 샘플: TR FHKST03010200
    time_itemchart: str = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    # 당일 시간대별 체결 요약 — 공식 샘플: TR FHPST01060000 (문서/샘플 기준)
    time_itemconclusion: str = "/uapi/domestic-stock/v1/quotations/inquire-time-itemconclusion"
    inquire_psbl_order: str = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
    # 레거시 전용 미체결 URL(일부 환경 404). 클라이언트는 inquire_daily_ccld(CCLD_DVSN=02) 사용.
    inquire_nccs: str = "/uapi/domestic-stock/v1/trading/inquire-nccs"
    inquire_daily_ccld: str = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"


@dataclass(frozen=True)
class DomesticTrIds:
    """모의/실전 TR_ID 쌍 (국내주식)."""

    balance_paper: str = "VTTC8434R"
    balance_live: str = "TTTC8434R"
    quote_paper: str = "FHKST01010100"
    quote_live: str = "FHKST01010100"
    psbl_order_paper: str = "VTTC8908R"
    psbl_order_live: str = "TTTC8908R"
    nccs_paper: str = "VTTC8003R"
    nccs_live: str = "TTTC8003R"
    # 일별주문체결(3개월 이내): 공식 샘플·포털 기준 모의 VTTC0081R / 실전 TTTC0081R
    daily_ccld_paper: str = "VTTC0081R"
    daily_ccld_live: str = "TTTC0081R"
    buy_paper: str = "VTTC0802U"
    buy_live: str = "TTTC0802U"
    sell_paper: str = "VTTC0801U"
    sell_live: str = "TTTC0801U"
    cancel_paper: str = "VTTC0803U"
    cancel_live: str = "TTTC0803U"
    daily_chart_paper: str = "FHKST03010100"
    daily_chart_live: str = "FHKST03010100"
    # 주식당일분봉조회 — 모의/실전 동일 TR (open-trading-api inquire_time_itemchartprice)
    time_itemchart_paper: str = "FHKST03010200"
    time_itemchart_live: str = "FHKST03010200"
    time_itemconclusion_paper: str = "FHPST01060000"
    time_itemconclusion_live: str = "FHPST01060000"


def pick_tr(*, paper: str, live: str, base_url: str) -> str:
    return paper if is_paper_host(base_url) else live
