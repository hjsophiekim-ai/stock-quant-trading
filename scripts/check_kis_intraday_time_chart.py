"""
한국투자 Open API — 주식당일분봉조회(inquire-time-itemchartprice) 단독 점검.

사용 예:
  python scripts/check_kis_intraday_time_chart.py --symbol 005930 --pages 2

.env 의 KIS_APP_KEY / KIS_APP_SECRET 및 TRADING_MODE 에 맞는 base URL(모의: KIS_MOCK_BASE_URL)을 사용합니다.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from zoneinfo import ZoneInfo

from app.clients.kis_client import KISClientError
from app.clients.kis_parsers import output2_rows
from app.logging import setup_logging
from app.scheduler.kis_intraday import _cursor_before_minute, _hhmmss_from_ts, kis_time_chart_row_to_bar
from scripts.kis_script_utils import (
    build_kis_client,
    issue_token_or_exit,
    load_app_settings,
    resolved_kis_base_url,
)

_KST = ZoneInfo("Asia/Seoul")
_STOCK_MKT = "J"


def _main() -> None:
    setup_logging()
    logger = logging.getLogger("scripts.check_kis_intraday_time_chart")
    ap = argparse.ArgumentParser(description="KIS 당일 분봉 API 단독 호출 점검")
    ap.add_argument("--symbol", default="005930", help="6자리 종목코드")
    ap.add_argument("--pages", type=int, default=2, help="연속 페이지 시도 횟수(상한)")
    ap.add_argument("--include-past-data", default="Y", dest="include_past_data", help="FID_PW_DATA_INCU_YN (Y/N)")
    args = ap.parse_args()

    cfg = load_app_settings()
    base_url = resolved_kis_base_url(cfg)
    token = issue_token_or_exit(cfg, base_url=base_url, logger=logger)
    client = build_kis_client(cfg, base_url=base_url, access_token=token)

    sym = str(args.symbol).strip().zfill(6)[:6]
    cursor = datetime.now(_KST).strftime("%H%M%S")
    merged: list[dict] = []
    out_pages: list[dict[str, object]] = []

    for page in range(max(1, int(args.pages))):
        try:
            payload = client.get_time_itemchartprice(
                market_div_code=_STOCK_MKT,
                symbol=sym,
                input_hour_hhmmss=cursor,
                include_past_data=str(args.include_past_data).strip() or "Y",
                etc_cls_code="",
            )
        except KISClientError as exc:
            ctx = getattr(exc, "kis_context", {}) or {}
            print(
                json.dumps(
                    {
                        "ok": False,
                        "page": page + 1,
                        "symbol": sym,
                        "error": str(exc),
                        "http_status": ctx.get("http_status"),
                        "path": ctx.get("path"),
                        "tr_id": ctx.get("tr_id"),
                        "params": ctx.get("params"),
                        "rate_limit": ctx.get("rate_limit"),
                        "rt_cd": ctx.get("rt_cd"),
                        "msg_cd": ctx.get("msg_cd"),
                        "msg1": ctx.get("msg1"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            raise SystemExit(1) from exc

        batch = output2_rows(payload)
        hours: list[str] = []
        for row in batch:
            h = row.get("stck_cntg_hour") or row.get("bsop_hour") or row.get("cntg_hour")
            if h is not None:
                hours.append(str(h).strip().zfill(6)[:6])

        out_pages.append(
            {
                "page": page + 1,
                "http_status": 200,
                "rt_cd": str(payload.get("rt_cd") or ""),
                "msg_cd": str(payload.get("msg_cd") or ""),
                "msg1": str(payload.get("msg1") or ""),
                "output2_row_count": len(batch),
                "first_stck_cntg_hour": hours[0] if hours else None,
                "last_stck_cntg_hour": hours[-1] if hours else None,
                "path": client.endpoints.time_itemchart,
                "tr_id": client._resolve_tr_id(
                    paper_tr_id=client.tr_ids.time_itemchart_paper,
                    live_tr_id=client.tr_ids.time_itemchart_live,
                ),
                "params": {
                    "FID_COND_MRKT_DIV_CODE": _STOCK_MKT,
                    "FID_INPUT_ISCD": sym,
                    "FID_INPUT_HOUR_1": cursor,
                    "FID_PW_DATA_INCU_YN": str(args.include_past_data).strip() or "Y",
                    "FID_ETC_CLS_CODE": "",
                },
            }
        )
        merged.extend(batch)
        if not batch:
            break
        oldest_ts = None
        for row in batch:
            today = datetime.now(_KST).strftime("%Y%m%d")
            bar = kis_time_chart_row_to_bar(row, symbol=sym, default_date_yyyymmdd=today)
            if bar is None:
                continue
            ts = bar["date"]
            if oldest_ts is None or ts < oldest_ts:
                oldest_ts = ts
        if oldest_ts is None:
            break
        cursor = _cursor_before_minute(_hhmmss_from_ts(oldest_ts))

    print(
        json.dumps(
            {
                "ok": True,
                "symbol": sym,
                "trading_mode": cfg.trading_mode,
                "api_base": base_url,
                "pages_requested": int(args.pages),
                "merged_output2_rows": len(merged),
                "per_page": out_pages,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    _main()
