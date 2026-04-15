"""Paper 인트라데이: 리스크·버킷 기반 매수 수량(최소 1주)."""

from __future__ import annotations


def compute_intraday_buy_quantity(
    *,
    price_krw: float,
    stop_loss_pct_points: float,
    equity_krw: float,
    intraday_budget_krw: float,
    max_position_pct: float,
    risk_per_trade_pct: float,
    fallback_qty: int,
    max_shares_cap: int = 500,
) -> int:
    """
    - risk_per_trade_pct: 계좌 평가금 대비 1회 허용 손실 비율(%).
    - stop_loss_pct_points: 가격 대비 손절 폭(% 포인트), 예: 0.5 → 0.5%.
    - max_position_pct: intraday_budget_krw 대비 단일 종목 최대 투입(%).
    """
    px = float(price_krw)
    if px <= 0:
        return max(1, int(fallback_qty))
    eq = max(0.0, float(equity_krw))
    budget = max(0.0, float(intraday_budget_krw))
    if budget <= 0 and eq > 0:
        budget = eq
    sl_pts = max(0.05, float(stop_loss_pct_points))
    stop_dist = px * (sl_pts / 100.0)
    risk_cash = eq * (max(0.0, float(risk_per_trade_pct)) / 100.0)
    qty_risk = int(risk_cash / stop_dist) if stop_dist > 0 else 1
    cap_notional = budget * (max(0.0, float(max_position_pct)) / 100.0)
    qty_cap = int(cap_notional / px) if px > 0 else 1
    cap = max(1, int(max_shares_cap))
    q = min(max(1, qty_risk), max(1, qty_cap), cap)
    if q < 1:
        return max(1, int(fallback_qty))
    return max(1, q)
