"""
성과 API용 체결 리플레이·수익률 계산.

- 매도 체결별: **FIFO** 실현손익, 매수·매도 수수료 및 **매도세(KRX)** 반영.
- gross_pnl: 매도 체결가×수량 − 매수 순가(매수 수수료 제외한 원가) 기준 가격차 손익.
- net_pnl: 매도 순현금(수수료·세금 차감) − 매수 총비용(수수료 포함) 기준 FIFO 손익.
- 체결 행에 수수료/세금 컬럼이 있으면 우선 사용, 없으면 설정 비율(KIS_*, KRX_*)로 추정.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# --- Fees: optional column names (KIS/내부 확장 대비) ---
_FEE_KEYS = (
    "fee",
    "fee_amt",
    "tot_fee",
    "commission",
    "prcpay_fee",
    "FNCN_FEE",
    "RSC_FEE",
    "ccld_fee",
)
_TAX_KEYS = ("tax", "trtx", "sell_tax", "SELL_TAX", "scnd_sell_tax")


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x >= 0 else None


def extract_explicit_fees(row: dict[str, Any], side: str) -> tuple[float | None, float | None, str]:
    """
    반환: (fee_amount, tax_amount, source_tag)
    tax는 매도에서만 조회; 매수 행에서는 세금 컬럼을 무시합니다.
    """
    fee_amt: float | None = None
    tax_amt: float | None = None
    for k in _FEE_KEYS:
        if k in row:
            fee_amt = _to_float(row.get(k))
            if fee_amt is not None:
                break
    if side == "sell":
        for k in _TAX_KEYS:
            if k in row:
                tax_amt = _to_float(row.get(k))
                if tax_amt is not None:
                    break
    src = "explicit_columns" if (fee_amt is not None or tax_amt is not None) else "estimated_rates"
    if side != "sell":
        tax_amt = None
    return fee_amt, tax_amt, src


def _estimate_buy_cost(
    qty: int,
    gross: float,
    row: dict[str, Any],
    buy_fee_rate: float,
) -> tuple[float, float, str]:
    """반환: (총 매입비용=체결금액+매수수수료, 매수수수료, 출처)"""
    fee_e, _, src = extract_explicit_fees(row, "buy")
    if fee_e is not None:
        return gross + fee_e, fee_e, src
    fee = gross * float(buy_fee_rate)
    return gross + fee, fee, "estimated_rates"


def _estimate_sell_net(
    qty: int,
    gross: float,
    row: dict[str, Any],
    sell_fee_rate: float,
    sell_tax_rate: float,
) -> tuple[float, float, float, str]:
    """
    반환: (매도 순현금 유입, 매도수수료, 매도세, 출처요약)
    """
    fee_e, tax_e, src = extract_explicit_fees(row, "sell")
    if fee_e is not None or tax_e is not None:
        f = fee_e or 0.0
        t = tax_e or 0.0
        return gross - f - t, f, t, "explicit_columns"
    f = gross * float(sell_fee_rate)
    t = gross * float(sell_tax_rate)
    return gross - f - t, f, t, "estimated_rates"


@dataclass
class FifoTradeRow:
    trade_id: str
    symbol: str
    strategy_id: str
    quantity: int
    price: float
    filled_at: str
    gross_sell_krw: float
    gross_pnl: float
    net_pnl: float
    buy_fee: float
    sell_fee: float
    tax: float
    realized_pnl_fifo: float
    realized_pnl_avg_cost: float
    fee_input_mode: str


@dataclass
class FifoReplayResult:
    trades: list[FifoTradeRow]
    gross_realized_pnl: float
    net_realized_pnl: float
    total_buy_fees: float
    total_sell_fees: float
    total_taxes: float
    fifo_total_realized: float
    avg_cost_total_realized: float
    replay_warnings: list[str]
    fee_mode_counts: dict[str, int] = field(default_factory=dict)


def _sort_fills_chrono(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda f: (
            str(f.get("ord_dt") or ""),
            str(f.get("ord_tmd") or ""),
            str(f.get("exec_id") or ""),
        ),
    )


def fifo_and_avg_cost_replay(
    fills: list[dict[str, Any]],
    *,
    buy_fee_rate: float,
    sell_fee_rate: float,
    sell_tax_rate: float,
) -> FifoReplayResult:
    """
    시간순 체결. FIFO lot: (수량, 매입총비용(수수료포함), 해당 lot 매수수수료).
    """
    rows = _sort_fills_chrono(fills)
    fifo_lots: dict[str, deque[tuple[int, float, float]]] = defaultdict(deque)
    qty_ac: dict[str, int] = defaultdict(int)
    avg_ac: dict[str, float] = defaultdict(float)

    out_trades: list[FifoTradeRow] = []
    warnings: list[str] = []
    fee_mode_counts: dict[str, int] = defaultdict(int)
    fifo_total = 0.0
    avg_total = 0.0
    gross_total = 0.0
    total_buy_fees = 0.0
    total_sell_fees = 0.0
    total_taxes = 0.0
    idx = 0

    for r in rows:
        sym = str(r.get("symbol") or "").strip()
        side = str(r.get("side") or "").lower()
        sid = str(r.get("strategy_id") or "unknown")
        try:
            qty = int(r.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        try:
            px = float(r.get("price") or 0.0)
        except (TypeError, ValueError):
            continue
        if not sym or qty <= 0 or px <= 0:
            continue

        gross = float(qty) * px
        tid = str(r.get("exec_id") or f"fill-{idx}")
        filled_at = f"{r.get('ord_dt', '')}{str(r.get('ord_tmd', '')).ljust(6, '0')[:6]}"
        idx += 1

        if side == "buy":
            tot_cost, buy_fee, fmode = _estimate_buy_cost(qty, gross, r, buy_fee_rate)
            fifo_lots[sym].append((qty, tot_cost, buy_fee))
            fee_mode_counts[fmode] += 1
            total_buy_fees += buy_fee
            old_q = qty_ac[sym]
            old_a = avg_ac[sym]
            new_q = old_q + qty
            new_avg = ((old_a * old_q) + (px * qty)) / new_q if new_q > 0 else 0.0
            qty_ac[sym] = new_q
            avg_ac[sym] = new_avg
            continue

        if side != "sell":
            continue

        net_in, sell_f, tax_v, smode = _estimate_sell_net(qty, gross, r, sell_fee_rate, sell_tax_rate)
        fee_mode_counts[smode] += 1
        total_sell_fees += sell_f
        total_taxes += tax_v
        per_net = net_in / float(qty) if qty else 0.0
        gross_sell_krw = gross

        dq = fifo_lots[sym]
        rem = qty
        fifo_pnl = 0.0
        gross_pnl_trade = 0.0
        buy_fee_trade = 0.0
        if not dq:
            warnings.append(f"sell_without_lots:{sym}:exec={tid}")
        while rem > 0 and dq:
            lot_q, lot_cost, lot_buy_fee = dq[0]
            take = min(rem, lot_q)
            unit_cost_incl = lot_cost / float(lot_q)
            unit_pure = (lot_cost - lot_buy_fee) / float(lot_q)
            cost_part = unit_cost_incl * float(take)
            pure_cost_part = unit_pure * float(take)
            proceeds_part = per_net * float(take)
            gross_sell_part = px * float(take)
            fifo_pnl += proceeds_part - cost_part
            gross_pnl_trade += gross_sell_part - pure_cost_part
            buy_fee_trade += lot_buy_fee * (float(take) / float(lot_q))
            if take >= lot_q:
                dq.popleft()
            else:
                dq[0] = (lot_q - take, lot_cost - cost_part, lot_buy_fee * (1.0 - float(take) / float(lot_q)))
            rem -= take
        if rem > 0:
            warnings.append(f"sell_exceeds_fifo_lots:{sym}:remaining_qty={rem}:exec={tid}")

        base_q = qty_ac[sym]
        base_avg = avg_ac[sym]
        eff_qty = min(base_q, qty) if base_q > 0 else qty
        avg_pnl_raw = (px - base_avg) * eff_qty if base_q > 0 else 0.0
        avg_pnl = avg_pnl_raw - sell_f - tax_v if base_q > 0 else 0.0
        qty_ac[sym] = max(base_q - qty, 0)
        if qty_ac[sym] == 0:
            avg_ac[sym] = 0.0

        fifo_total += fifo_pnl
        avg_total += avg_pnl
        gross_total += gross_pnl_trade

        out_trades.append(
            FifoTradeRow(
                trade_id=tid,
                symbol=sym,
                strategy_id=sid,
                quantity=qty,
                price=px,
                filled_at=filled_at,
                gross_sell_krw=round(gross_sell_krw, 4),
                gross_pnl=round(gross_pnl_trade, 4),
                net_pnl=round(fifo_pnl, 4),
                buy_fee=round(buy_fee_trade, 4),
                sell_fee=round(sell_f, 4),
                tax=round(tax_v, 4),
                realized_pnl_fifo=round(fifo_pnl, 4),
                realized_pnl_avg_cost=round(avg_pnl, 4),
                fee_input_mode=f"{smode}",
            )
        )

    return FifoReplayResult(
        trades=out_trades,
        gross_realized_pnl=round(gross_total, 4),
        net_realized_pnl=round(fifo_total, 4),
        total_buy_fees=round(total_buy_fees, 4),
        total_sell_fees=round(total_sell_fees, 4),
        total_taxes=round(total_taxes, 4),
        fifo_total_realized=round(fifo_total, 4),
        avg_cost_total_realized=round(avg_total, 4),
        replay_warnings=warnings,
        fee_mode_counts=dict(fee_mode_counts),
    )


def fifo_trade_rows_as_dicts(replay: FifoReplayResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for t in replay.trades:
        pnl = t.net_pnl
        result = "win" if pnl > 0 else "loss" if pnl < 0 else "flat"
        rows.append(
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "strategy_id": t.strategy_id,
                "pnl": t.net_pnl,
                "gross_pnl": t.gross_pnl,
                "net_pnl": t.net_pnl,
                "fee": round(t.buy_fee + t.sell_fee, 4),
                "buy_fee": t.buy_fee,
                "sell_fee": t.sell_fee,
                "tax": t.tax,
                "gross_sell_krw": t.gross_sell_krw,
                "realized_pnl_fifo": t.realized_pnl_fifo,
                "realized_pnl_avg_cost": t.realized_pnl_avg_cost,
                "result": result,
                "quantity": t.quantity,
                "price": t.price,
                "filled_at": t.filled_at,
                "fee_input_mode": t.fee_input_mode,
            }
        )
    rows.reverse()
    return rows


def sort_pnl_rows_by_ts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _key(r: dict[str, Any]) -> str:
        return str(r.get("ts_utc") or "")

    return sorted(rows, key=_key)


def _parse_ts_utc(r: dict[str, Any]) -> datetime | None:
    ts = r.get("ts_utc")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _monday_utc(d: datetime) -> datetime:
    dd = d.date()
    monday = dd - timedelta(days=dd.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


def _month_floor_utc(d: datetime) -> datetime:
    return datetime(d.year, d.month, 1, tzinfo=timezone.utc)


@dataclass
class EquityReturnBundle:
    daily_return_pct: float
    weekly_return_pct: float
    monthly_return_pct: float
    cumulative_return_pct: float
    max_drawdown_pct: float
    equity_start: float | None
    equity_end: float | None
    weekly_anchor_ts: str | None
    monthly_anchor_ts: str | None
    notes: list[str]


def compute_equity_returns(
    pnl_rows_sorted: list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> EquityReturnBundle:
    """
    수익률 정의(필터 구간 내 `pnl_history.jsonl` 지점 사용):

    - **cumulative_return_pct**: (마지막 equity / 첫 equity - 1) * 100, 둘 다 > 0 일 때.
    - **weekly_return_pct**: (마지막 equity / 해당 주 월요일 00:00 UTC 이후 첫 지점 equity - 1) * 100.
    - **monthly_return_pct**: (마지막 equity / 해당 월 1일 00:00 UTC 이후 첫 지점 equity - 1) * 100.
    - **daily_return_pct**: 마지막 행의 `daily_pnl_pct`가 있으면 우선; 없으면 직전 대비.
    - **max_drawdown_pct**: 구간 내 equity 양수 곡선에 대해 롤링 피크 대비 최대 낙폭(%).
    """
    notes: list[str] = []
    rows = [r for r in pnl_rows_sorted if _parse_ts_utc(r) is not None]
    equities = [float(r.get("equity") or 0.0) for r in rows]

    snap_daily = float(snapshot.get("daily_pnl_pct") or 0.0)
    snap_cum = float(snapshot.get("cumulative_pnl_pct") or 0.0)

    if len(rows) < 1:
        notes.append("pnl_history_empty_using_snapshot_only")
        return EquityReturnBundle(
            daily_return_pct=round(snap_daily, 4),
            weekly_return_pct=0.0,
            monthly_return_pct=0.0,
            cumulative_return_pct=round(snap_cum, 4),
            max_drawdown_pct=0.0,
            equity_start=None,
            equity_end=None,
            weekly_anchor_ts=None,
            monthly_anchor_ts=None,
            notes=notes,
        )

    last = rows[-1]
    eq_end = float(last.get("equity") or 0.0)
    ts_end = _parse_ts_utc(last) or datetime.now(timezone.utc)

    daily = float(last.get("daily_pnl_pct") or 0.0)
    if daily == 0.0 and len(rows) >= 2:
        eq_prev = float(rows[-2].get("equity") or 0.0)
        if eq_prev > 0 and eq_end > 0:
            daily = ((eq_end / eq_prev) - 1.0) * 100.0
            notes.append("daily_return_from_equity_delta_last_two_points")

    eq_start = float(rows[0].get("equity") or 0.0)
    cum = 0.0
    if eq_start > 0 and eq_end > 0:
        cum = ((eq_end / eq_start) - 1.0) * 100.0
    else:
        notes.append("cumulative_skipped_non_positive_equity_using_snapshot")
        cum = snap_cum

    mon = _monday_utc(ts_end)
    weekly_anchor_ts: str | None = None
    eq_week: float | None = None
    for r in rows:
        t = _parse_ts_utc(r)
        if t is None:
            continue
        if t >= mon:
            eq_week = float(r.get("equity") or 0.0)
            weekly_anchor_ts = str(r.get("ts_utc"))
            break
    weekly = 0.0
    if eq_week is not None and eq_week > 0 and eq_end > 0:
        weekly = ((eq_end / eq_week) - 1.0) * 100.0
    else:
        notes.append("weekly_return_unavailable_insufficient_history")

    mf = _month_floor_utc(ts_end)
    monthly_anchor_ts = None
    eq_month: float | None = None
    for r in rows:
        t = _parse_ts_utc(r)
        if t is None:
            continue
        if t >= mf:
            eq_month = float(r.get("equity") or 0.0)
            monthly_anchor_ts = str(r.get("ts_utc"))
            break
    monthly = 0.0
    if eq_month is not None and eq_month > 0 and eq_end > 0:
        monthly = ((eq_end / eq_month) - 1.0) * 100.0
    else:
        notes.append("monthly_return_unavailable_insufficient_history")

    pos_eq = [e for e in equities if e > 0]
    mdd = _rolling_max_drawdown_pct(pos_eq) if pos_eq else 0.0

    return EquityReturnBundle(
        daily_return_pct=round(daily, 4),
        weekly_return_pct=round(weekly, 4),
        monthly_return_pct=round(monthly, 4),
        cumulative_return_pct=round(cum, 4),
        max_drawdown_pct=round(mdd, 4),
        equity_start=eq_start if eq_start > 0 else None,
        equity_end=eq_end if eq_end > 0 else None,
        weekly_anchor_ts=weekly_anchor_ts,
        monthly_anchor_ts=monthly_anchor_ts,
        notes=notes,
    )


def _rolling_max_drawdown_pct(equities: list[float]) -> float:
    if not equities:
        return 0.0
    peak = equities[0]
    worst = 0.0
    for e in equities:
        if e > peak:
            peak = e
        if peak > 0:
            dd = ((e / peak) - 1.0) * 100.0
            if dd < worst:
                worst = dd
    return float(worst)
