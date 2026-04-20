"""final_betting_v1 체결 기반 간단 성과·헬스(페이퍼). 곡선 맞춤 없이 최근 실현 손익으로만 판단."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

OutcomeKind = Literal["profit", "stop", "flat"]


def classify_fb_exit_outcome(reason: str, *, pnl_pct: float) -> tuple[OutcomeKind, str]:
    """청산 사유·손익률로 outcome 분류 (쿨다운·통계 공통)."""
    r = (reason or "").lower()
    if "take_profit" in r or "gap_up" in r:
        return "profit", "after_profit_exit"
    if "gap_down" in r or "flush" in r or "stop" in r:
        return "stop", "after_stop_exit"
    if pnl_pct >= 0.12:
        return "profit", "after_profit_exit_pnl"
    if pnl_pct <= -0.18:
        return "stop", "after_loss_exit_pnl"
    return "flat", "after_flat_exit"


def record_fb_sell_outcome(
    carry: dict[str, Any],
    *,
    symbol: str,
    sold_qty: int,
    fill_px: float,
    entry_px: float,
    reason: str,
    reference_close: float | None = None,
    order_request_price: float | None = None,
    executed_avg_fill_price: float | None = None,
    pnl_price_source: str = "unspecified",
) -> None:
    pnl = (float(fill_px) - float(entry_px)) * int(sold_qty)
    row = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": str(symbol),
        "sold_qty": int(sold_qty),
        "fill_px": round(float(fill_px), 6),
        "entry_px": round(float(entry_px), 6),
        "pnl_krw": round(float(pnl), 2),
        "reason": str(reason or ""),
        "reference_close": round(float(reference_close), 6) if reference_close is not None else None,
        "order_request_price": round(float(order_request_price), 6) if order_request_price is not None else None,
        "executed_avg_fill_price": round(float(executed_avg_fill_price), 6)
        if executed_avg_fill_price is not None
        else None,
        "pnl_price_source": str(pnl_price_source),
    }
    ledger: list[dict[str, Any]] = list(carry.get("fb_perf_ledger") or [])
    ledger.append(row)
    carry["fb_perf_ledger"] = ledger[-200:]


def fb_performance_snapshot(carry: dict[str, Any], *, last_n: int = 40) -> dict[str, Any]:
    """최근 체결만 사용한 요약 통계."""
    rows = list(carry.get("fb_perf_ledger") or [])
    tail = rows[-max(1, last_n) :] if rows else []
    if not tail:
        return {
            "trade_count": 0,
            "win_rate": None,
            "avg_win_krw": None,
            "avg_loss_krw": None,
            "profit_factor": None,
            "expectancy_krw": None,
            "max_drawdown_krw_proxy": None,
        }
    pnls = [float(r.get("pnl_krw") or 0.0) for r in tail]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    pf = (gross_win / gross_loss) if gross_loss > 1e-9 else None
    return {
        "trade_count": len(tail),
        "win_rate": round(len(wins) / len(tail), 4) if tail else None,
        "avg_win_krw": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss_krw": round(sum(losses) / len(losses), 2) if losses else None,
        "profit_factor": round(float(pf), 4) if pf is not None else None,
        "expectancy_krw": round(sum(pnls) / len(pnls), 4) if pnls else None,
        "max_drawdown_krw_proxy": _max_dd_proxy(pnls),
    }


def _max_dd_proxy(pnls: list[float]) -> float | None:
    if not pnls:
        return None
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
    return round(float(max_dd), 2)


def fb_health_size_multiplier(carry: dict[str, Any]) -> tuple[str, float]:
    """
    strong / neutral / weak — 약하면 비중만 소폭 축소 (전략 비활성화 없음).
    """
    snap = fb_performance_snapshot(carry, last_n=40)
    n = int(snap.get("trade_count") or 0)
    if n < 8:
        return "neutral", 1.0
    pf = snap.get("profit_factor")
    wr = snap.get("win_rate")
    if pf is None:
        return "neutral", 0.92
    pf_f = float(pf)
    wr_f = float(wr) if wr is not None else 0.0
    if pf_f >= 1.12 and wr_f >= 0.38:
        return "strong", 1.0
    if pf_f <= 0.82 or wr_f <= 0.28:
        return "weak", 0.72
    return "neutral", 0.9


def ensure_fb_intraday_meta(carry: dict[str, Any], today_kst: str) -> dict[str, Any]:
    meta = carry.get("fb_intraday_meta")
    if not isinstance(meta, dict) or meta.get("date_kst") != today_kst:
        meta = {"date_kst": today_kst, "stopout_counts": {}}
        carry["fb_intraday_meta"] = meta
    meta.setdefault("stopout_counts", {})
    return meta


def apply_fb_dynamic_cooldown(
    *,
    cfg: Any,
    state: Any,
    carry: dict[str, Any],
    symbol: str,
    reason: str,
    pnl_pct: float,
    today_kst: str,
) -> tuple[int, str]:
    """동적 쿨다운(분) + 사유 코드. stop 연속 시 더 길게."""
    meta = ensure_fb_intraday_meta(carry, today_kst)
    counts: dict[str, Any] = meta["stopout_counts"]
    kind, subreason = classify_fb_exit_outcome(reason, pnl_pct=pnl_pct)
    if kind == "profit":
        mins = int(getattr(cfg, "paper_final_betting_cd_after_profit_minutes", 15))
    elif kind == "stop":
        prev = int(counts.get(symbol, 0) or 0)
        if prev >= 1:
            mins = int(getattr(cfg, "paper_final_betting_cd_after_repeat_stop_minutes", 90))
        else:
            mins = int(getattr(cfg, "paper_final_betting_cd_after_stop_minutes", 32))
        counts[str(symbol)] = prev + 1
    else:
        mins = (
            int(getattr(cfg, "paper_final_betting_cd_after_profit_minutes", 15))
            + int(getattr(cfg, "paper_final_betting_cd_after_stop_minutes", 32))
        ) // 2
    until = datetime.now(timezone.utc) + timedelta(minutes=max(1, mins))
    state.cooldown_until_iso[str(symbol)] = until.isoformat()
    trace = carry.setdefault("fb_cooldown_trace", {})
    trace[str(symbol)] = {
        "cooldown_reason": subreason,
        "cooldown_minutes": mins,
        "cooldown_until_iso": state.cooldown_until_iso[str(symbol)],
        "outcome_kind": kind,
    }
    return mins, subreason
