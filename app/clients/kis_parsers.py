"""KIS JSON 응답 파싱 (민감 필드는 로그하지 말 것)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.brokers.base_broker import OpenOrder


def parse_kis_ord_datetime_to_utc(ord_dt: str, ord_tmd: str) -> datetime:
    """KIS 일별체결 행의 ord_dt(YYYYMMDD) + ord_tmd(HHMMSS…) → UTC datetime (파싱 실패 시 now)."""
    try:
        if len(ord_dt) == 8 and len(ord_tmd) >= 6:
            return datetime.strptime(ord_dt + ord_tmd[:6], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return datetime.now(timezone.utc)


def rt_cd_ok(payload: dict[str, Any]) -> bool:
    return str(payload.get("rt_cd", "0")) in {"0", ""}


def business_error_detail(payload: dict[str, Any]) -> str:
    parts = [
        str(payload.get("msg1") or ""),
        str(payload.get("msg_cd") or ""),
    ]
    return " | ".join(p for p in parts if p).strip() or "Unknown KIS business error"


def is_kis_rate_limit(
    *,
    payload: dict[str, Any] | None = None,
    http_body: str = "",
    http_status: int = 0,
) -> bool:
    """
    EGW00201(초당 거래건수 초과) 등 rate limit 패턴.
    HTTP 500이어도 본문에 동일 코드가 올 수 있음.
    """
    chunks: list[str] = []
    if payload:
        chunks.extend(
            [
                str(payload.get("msg_cd") or ""),
                str(payload.get("msg1") or ""),
                str(payload.get("msg2") or ""),
                str(payload.get("rt_cd") or ""),
            ]
        )
    chunks.append(http_body or "")
    blob = " ".join(chunks).upper()
    if "EGW00201" in blob:
        return True
    low = " ".join(chunks).lower()
    if "초당" in low and ("거래" in low or "건수" in low):
        return True
    if "RATE LIMIT" in blob or "TOO MANY" in blob:
        return True
    _ = http_status  # 향후 특정 status 전용 분기용
    return False


def output1_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("output1")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def output2_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("output2")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def quote_from_price_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """inquire-price 응답에서 요약 필드만 추출."""
    out = payload.get("output")
    if not isinstance(out, dict):
        return {}
    keys = (
        "iscd",
        "prdt_name",
        "prpr",
        "bidp",
        "askp",
        "antc_cnpr",
        "vol_tnrt",
        "hts_avls",
    )
    return {k: out.get(k) for k in keys if k in out}


def balance_cash_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """잔고조회 output2 첫 행에서 예수금 관련 숫자 요약."""
    rows = output2_rows(payload)
    if not rows:
        return {}
    row = rows[0]
    pick = (
        "dnca_tot_amt",
        "nxdy_excc_amt",
        "prvs_rcdl_excc_amt",
        "tot_evlu_amt",
        "nass_amt",
        "pchs_amt_smtl",
        "evlu_amt_smtl",
    )
    return {k: row.get(k) for k in pick if k in row}


def positions_brief(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """보유 종목 요약 (output1)."""
    result: list[dict[str, Any]] = []
    for row in output1_rows(payload):
        sym = row.get("pdno")
        if not sym:
            continue
        result.append(
            {
                "pdno": sym,
                "prdt_name": row.get("prdt_name"),
                "hldg_qty": row.get("hldg_qty"),
                "ord_psbl_qty": row.get("ord_psbl_qty"),
                "pchs_avg_pric": row.get("pchs_avg_pric"),
                "prpr": row.get("prpr"),
            }
        )
    return result


def psbl_order_summary(payload: dict[str, Any]) -> dict[str, Any]:
    out = payload.get("output")
    if not isinstance(out, dict):
        return {}
    keys = (
        "ord_psbl_cash",
        "ord_psbl_qty",
        "ruse_psbl_amt",
        "nrcvb_buy_amt",
        "max_buy_amt",
    )
    return {k: out.get(k) for k in keys if k in out}


def _row_pick(row: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in row and row[k] is not None and str(row[k]).strip() != "":
            return row[k]
    low = {str(k).lower(): v for k, v in row.items()}
    for k in keys:
        lk = k.lower()
        if lk in low and low[lk] is not None and str(low[lk]).strip() != "":
            return low[lk]
    return None


def open_orders_from_nccs_payload(payload: dict[str, Any]) -> list[OpenOrder]:
    """국내주식 미체결내역 output1 → OpenOrder 리스트."""
    orders: list[OpenOrder] = []
    for row in output1_rows(payload):
        if not isinstance(row, dict):
            continue
        sym = str(_row_pick(row, "pdno", "PDNO") or "").strip()
        odno = str(_row_pick(row, "odno", "ODNO") or "").strip()
        org = str(_row_pick(row, "KRX_FWDG_ORD_ORGNO", "krx_fwdg_ord_orgno") or "").strip()
        if not sym or not odno:
            continue
        composite = f"{org}|{odno}" if org else odno
        try:
            ord_qty = int(float(_row_pick(row, "ord_qty", "ORD_QTY") or 0))
        except (TypeError, ValueError):
            ord_qty = 0
        if ord_qty <= 0:
            continue
        try:
            nccs = int(float(_row_pick(row, "tot_ccld_qty", "TOT_CCLD_QTY", "nccs_qty", "NCCS_QTY") or 0))
        except (TypeError, ValueError):
            nccs = 0
        try:
            rmn = _row_pick(row, "rmn_qty", "RMN_QTY", "psbl_qty", "PSBL_QTY")
            remaining = int(float(rmn)) if rmn is not None and str(rmn).strip() != "" else max(ord_qty - nccs, 0)
        except (TypeError, ValueError):
            remaining = max(ord_qty - nccs, 0)
        sb = str(_row_pick(row, "sll_buy_dvsn_cd", "SLL_BUY_DVSN_CD") or "02").strip()
        # 01 매도, 02 매수 (KIS 국내 일반 규칙)
        side: str = "sell" if sb == "01" else "buy"
        raw_pr = _row_pick(row, "ord_unpr", "ORD_UNPR")
        try:
            price = float(raw_pr) if raw_pr is not None and float(raw_pr) > 0 else None
        except (TypeError, ValueError):
            price = None
        t_raw = _row_pick(row, "ord_tmd", "ORD_TMD", "ord_dt", "ORD_DT")
        created = datetime.now(timezone.utc)
        if t_raw:
            ts = str(t_raw).strip()
            try:
                if len(ts) >= 14 and ts.isdigit():
                    created = datetime(
                        int(ts[0:4]),
                        int(ts[4:6]),
                        int(ts[6:8]),
                        int(ts[8:10]),
                        int(ts[10:12]),
                        int(ts[12:14]),
                        tzinfo=timezone.utc,
                    )
            except (ValueError, TypeError):
                pass
        rem = max(min(remaining, ord_qty), 0)
        if rem <= 0:
            continue
        orders.append(
            OpenOrder(
                order_id=composite,
                symbol=sym,
                side=side,
                quantity=ord_qty,
                remaining_quantity=rem,
                price=price,
                created_at=created,
            )
        )
    return orders


def order_output_brief(payload: dict[str, Any]) -> dict[str, Any]:
    out = payload.get("output")
    if not isinstance(out, dict):
        return {}
    return {
        "KRX_FWDG_ORD_ORGNO": out.get("KRX_FWDG_ORD_ORGNO") or out.get("krx_fwdg_ord_orgno"),
        "ODNO": out.get("ODNO") or out.get("odno"),
        "ORD_TMD": out.get("ORD_TMD") or out.get("ord_tmd"),
    }


def balance_snapshot_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """잔고조회: 현금·보유종목(평단·현재가·평가손익)."""
    cash = 0.0
    o2 = output2_rows(payload)
    if o2:
        row0 = o2[0]
        for key in ("ord_psbl_cash", "nrcvb_buy_amt", "dnca_tot_amt"):
            raw = row0.get(key)
            if raw is not None and str(raw).strip() != "":
                try:
                    cash = float(raw)
                    break
                except (TypeError, ValueError):
                    continue
    total_evlu = 0.0
    if o2:
        try:
            total_evlu = float(_row_pick(o2[0], "tot_evlu_amt", "TOT_EVLU_AMT") or 0)
        except (TypeError, ValueError):
            total_evlu = 0.0

    positions: list[dict[str, Any]] = []
    for row in output1_rows(payload):
        sym = str(_row_pick(row, "pdno", "PDNO") or "").strip()
        if not sym:
            continue
        try:
            qty = int(float(_row_pick(row, "hldg_qty", "HLDG_QTY") or 0))
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue
        try:
            avg = float(_row_pick(row, "pchs_avg_pric", "PCHS_AVG_PRIC") or 0)
        except (TypeError, ValueError):
            avg = 0.0
        try:
            prpr = float(_row_pick(row, "prpr", "PRPR") or 0)
        except (TypeError, ValueError):
            prpr = 0.0
        try:
            evlu_pfls = float(_row_pick(row, "evlu_pfls_amt", "EVLU_PFLS_AMT") or 0)
        except (TypeError, ValueError):
            evlu_pfls = 0.0
        try:
            evlu_amt = float(_row_pick(row, "evlu_amt", "EVLU_AMT") or 0)
        except (TypeError, ValueError):
            evlu_amt = 0.0
        positions.append(
            {
                "symbol": sym,
                "quantity": qty,
                "average_price": avg,
                "current_price": prpr,
                "unrealized_pnl_kis": evlu_pfls,
                "market_value": evlu_amt,
            }
        )

    return {
        "cash": cash,
        "total_evaluated_amt": total_evlu,
        "positions": positions,
    }


def normalized_fills_from_ccld_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """일별주문체결조회 output1 — 체결 분만 (CCLD_DVSN=01 로 조회한 응답 가정)."""
    out: list[dict[str, Any]] = []
    for row in output1_rows(payload):
        sym = str(_row_pick(row, "pdno", "PDNO") or "").strip()
        if not sym:
            continue
        try:
            ccld_qty = int(float(_row_pick(row, "ccld_qty", "CCLD_QTY", "tot_ccld_qty", "TOT_CCLD_QTY") or 0))
        except (TypeError, ValueError):
            ccld_qty = 0
        if ccld_qty <= 0:
            continue
        try:
            price = float(_row_pick(row, "ccld_untp", "CCLD_UNTP", "ord_unpr", "ORD_UNPR") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            continue
        sb = str(_row_pick(row, "sll_buy_dvsn_cd", "SLL_BUY_DVSN_CD") or "02").strip()
        side = "sell" if sb == "01" else "buy"
        odno = str(_row_pick(row, "odno", "ODNO", "orgn_odno", "ORGN_ODNO") or "").strip()
        odt = str(_row_pick(row, "ord_dt", "ORD_DT") or "")
        otm = str(_row_pick(row, "ord_tmd", "ORD_TMD", "ccld_tmd", "CCLD_TMD") or "")
        exec_id = f"{sym}|{odno}|{odt}|{otm}|{ccld_qty}|{price}|{side}"
        out.append(
            {
                "exec_id": exec_id,
                "symbol": sym,
                "side": side,
                "quantity": ccld_qty,
                "price": price,
                "order_no": odno,
                "ord_dt": odt,
                "ord_tmd": otm,
            }
        )
    return out
