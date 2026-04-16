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


# 주식당일분봉조회(FHKST03010200) FID_ETC_CLS_CODE
# — KIS Developers 국내주식 기본시세 문서·공식 Python 샘플(koreainvestment/open-trading-api)에서 "00" 사용.
# — GET 요청 시 빈 문자열은 prune 되어 필드 자체가 빠지므로(OPSQ2001) 반드시 비어 있지 않은 값으로 보냄.
TIME_ITEMCHART_FID_ETC_CLS_CODE = "00"


def pick_tr(*, paper: str, live: str, base_url: str) -> str:
    return paper if is_paper_host(base_url) else live


# --- 해외주식 (미국 등): koreainvestment/open-trading-api examples_user/overseas_stock/overseas_stock_functions.py 기준 ---


@dataclass(frozen=True)
class OverseasPricePaths:
    """해외주식 시세 (overseas-price v1)."""

    price: str = "/uapi/overseas-price/v1/quotations/price"
    search_info: str = "/uapi/overseas-price/v1/quotations/search-info"
    inquire_time_itemchartprice: str = "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"


@dataclass(frozen=True)
class OverseasStockPaths:
    """해외주식 주문·계좌 (overseas-stock v1)."""

    inquire_balance: str = "/uapi/overseas-stock/v1/trading/inquire-balance"
    inquire_nccs: str = "/uapi/overseas-stock/v1/trading/inquire-nccs"
    inquire_ccnl: str = "/uapi/overseas-stock/v1/trading/inquire-ccnl"
    order: str = "/uapi/overseas-stock/v1/trading/order"
    order_rvsecncl: str = "/uapi/overseas-stock/v1/trading/order-rvsecncl"


@dataclass(frozen=True)
class OverseasTrIds:
    """
    TR_ID: 공식 예제 overseas_stock_functions.py 및 legacy Sample01/kis_ovrseastk.py 주석과 동일.
    모의 호스트에서는 pick_tr 로 *_paper TR 을 선택.
    """

    # 해외주식 현재체결가 — 예제: 실전·모의 공통 HHDFS00000300
    price: str = "HHDFS00000300"
    # 해외주식 상품기본정보
    search_info: str = "CTPF1702R"
    # 해외주식분봉조회
    time_itemchart: str = "HHDFS76950200"
    balance_paper: str = "VTTS3012R"
    balance_live: str = "TTTS3012R"
    # legacy 주석: 모의 VTTS3018R
    nccs_paper: str = "VTTS3018R"
    nccs_live: str = "TTTS3018R"
    ccnl_paper: str = "VTTS3035R"
    ccnl_live: str = "TTTS3035R"
    us_buy_paper: str = "VTTT1002U"
    us_buy_live: str = "TTTT1002U"
    us_sell_paper: str = "VTTT1006U"
    us_sell_live: str = "TTTT1006U"
    us_order_rvsecncl_paper: str = "VTTT1004U"
    us_order_rvsecncl_live: str = "TTTT1004U"
