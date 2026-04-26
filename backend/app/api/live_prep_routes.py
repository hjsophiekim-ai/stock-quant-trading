from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.orders.models import OrderRequest
from app.risk.rules import RiskLimits, RiskRules, RiskSnapshot
from app.scheduler.equity_tracker import EquityTracker
from app.strategy.intraday_common import kst_now

from backend.app.clients.kis_client import build_kis_client_for_live_user
from backend.app.core.config import get_backend_settings, is_execution_mode_allowed, is_live_order_execution_configured
from backend.app.engine.live_prep_engine import generate_final_betting_shadow_candidates, generate_intraday_shadow_report
from backend.app.risk.audit import append_risk_event
from backend.app.services.live_exec_session_store import LiveExecSessionStore
from backend.app.services.live_liquidation_plan_store import LiquidationItem, LiquidationPlan, LiveLiquidationPlanStore
from backend.app.services.live_safety_state_store import LiveSafetyStateStore
from backend.app.services.live_sell_arm_store import SellOnlyArmState, SellOnlyArmStore

from .auth_routes import get_current_user_from_auth_header
from .broker_routes import get_broker_service
from .live_trading_routes import runtime_safety_validation_for_user_id
from ..services.live_prep_store import LiveCandidate, LiveCandidateStore

router = APIRouter(prefix="/live-prep", tags=["live-prep"])


class CandidateDecisionRequest(BaseModel):
    actor: str = Field(default="user", min_length=1, max_length=64)
    reason: str = Field(default="manual_approval", min_length=1, max_length=240)
    execution_mode: str | None = Field(default=None, min_length=0, max_length=64)


class SellOnlyArmRequest(BaseModel):
    enabled: bool
    armed_for_kst_date: str | None = Field(default=None, min_length=0, max_length=16)
    actor: str = Field(default="user", min_length=1, max_length=64)
    reason: str = Field(default="arm_sell_only", min_length=1, max_length=240)
    execution_mode: str | None = Field(default=None, min_length=0, max_length=64)


class LiquidationPrepareRequest(BaseModel):
    use_market_order: bool = True
    actor: str = Field(default="user", min_length=1, max_length=64)
    reason: str = Field(default="prepare_liquidation", min_length=1, max_length=240)
    execution_mode: str | None = Field(default=None, min_length=0, max_length=64)


class LiquidationExecuteRequest(BaseModel):
    confirm: str = Field(min_length=3, max_length=80)
    actor: str = Field(default="user", min_length=1, max_length=64)
    reason: str = Field(default="execute_liquidation", min_length=1, max_length=240)
    execution_mode: str | None = Field(default=None, min_length=0, max_length=64)


def _current_user(authorization: str | None):
    try:
        return get_current_user_from_auth_header(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except HTTPException:
        raise


def _store() -> LiveCandidateStore:
    cfg = get_backend_settings()
    return LiveCandidateStore(cfg.live_prep_candidates_store_json)


def _arm_store() -> SellOnlyArmStore:
    cfg = get_backend_settings()
    return SellOnlyArmStore(cfg.live_prep_sell_only_arm_store_json)


def _plan_store() -> LiveLiquidationPlanStore:
    cfg = get_backend_settings()
    return LiveLiquidationPlanStore(cfg.live_prep_liquidation_plans_store_json)


def _append_event(event_type: str, payload: dict[str, Any]) -> None:
    cfg = get_backend_settings()
    append_risk_event(
        cfg.risk_events_jsonl,
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **payload,
        },
    )


def _require_live_prep_enabled() -> None:
    cfg = get_backend_settings()
    if not is_execution_mode_allowed(cfg):
        raise HTTPException(status_code=403, detail="EXECUTION_MODE/TRADING_MODE 조합이 허용되지 않습니다.")
    if (cfg.trading_mode or "").lower() != "live":
        raise HTTPException(status_code=403, detail="TRADING_MODE=live 에서만 사용할 수 있습니다.")
    if (cfg.execution_mode or "").lower() not in {"live_shadow", "live_manual_approval"}:
        raise HTTPException(status_code=403, detail="EXECUTION_MODE=live_shadow 또는 live_manual_approval 만 허용합니다.")


def _effective_execution_mode_for_user(user_id: str, hint_execution_mode: str | None = None) -> str | None:
    cfg = get_backend_settings()
    mode = (cfg.execution_mode or "").strip().lower()
    if mode in {"live_shadow", "live_manual_approval"}:
        return mode
    st = LiveExecSessionStore(cfg.live_exec_sessions_store_json)
    sess = st.get_active(user_id) or st.get_latest(user_id)
    if sess is None:
        m2 = (hint_execution_mode or "").strip().lower()
        return m2 if m2 in {"live_shadow", "live_manual_approval"} else None
    m = (sess.execution_mode or "").strip().lower()
    return m if m in {"live_shadow", "live_manual_approval"} else None


def _require_live_prep_enabled_for_user(user_id: str, hint_execution_mode: str | None = None) -> str:
    cfg = get_backend_settings()
    if (cfg.trading_mode or "").lower() != "live":
        raise HTTPException(status_code=403, detail="TRADING_MODE=live 에서만 사용할 수 있습니다.")
    eff = _effective_execution_mode_for_user(user_id, hint_execution_mode=hint_execution_mode)
    if eff not in {"live_shadow", "live_manual_approval"}:
        raise HTTPException(status_code=403, detail="live 실행 모드가 설정되지 않았습니다. (live_shadow / live_manual_approval)")
    return eff


@router.get("/status")
def live_prep_status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    user = _current_user(authorization)
    live_status = runtime_safety_validation_for_user_id(cfg, user.id)
    safety_state = LiveSafetyStateStore(cfg.live_trading_safety_state_store_json).get(user.id)
    return {
        "trading_mode": cfg.trading_mode,
        "execution_mode": cfg.execution_mode,
        "live_safety": {
            "live_trading_flag": bool(safety_state.live_trading_flag),
            "secondary_confirm_flag": bool(safety_state.secondary_confirm_flag),
            "extra_approval_flag": bool(safety_state.extra_approval_flag),
            "live_emergency_stop": bool(safety_state.live_emergency_stop),
        },
        "live_ready_for_submit": bool(live_status.get("ok")),
        "blockers": list(live_status.get("blockers") or []),
        "blocker_details": list(live_status.get("blocker_details") or []),
    }


@router.get("/sell-only-arm/status")
def sell_only_arm_status(
    authorization: str | None = Header(default=None),
    execution_mode: str | None = Query(default=None),
) -> dict[str, Any]:
    user = _current_user(authorization)
    _require_live_prep_enabled_for_user(user.id, hint_execution_mode=execution_mode)
    st = _arm_store().get(user.id)
    return {"ok": True, "state": asdict(st) if st is not None else None}


@router.post("/sell-only-arm")
def set_sell_only_arm(payload: SellOnlyArmRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = _current_user(authorization)
    _require_live_prep_enabled_for_user(user.id, hint_execution_mode=payload.execution_mode)
    now = kst_now()
    tomorrow = (now.date().toordinal() + 1)
    default_armed_day = datetime.fromordinal(tomorrow).strftime("%Y%m%d")
    armed_day = str(payload.armed_for_kst_date or default_armed_day)
    store = _arm_store()
    prev = store.get(user.id)
    st = SellOnlyArmState(
        user_id=user.id,
        enabled=bool(payload.enabled),
        scope="final_betting_only",
        armed_for_kst_date=armed_day,
        created_at_utc=(prev.created_at_utc if prev is not None else datetime.now(timezone.utc).isoformat()),
        updated_at_utc=datetime.now(timezone.utc).isoformat(),
        actor=str(payload.actor or user.id),
        reason=str(payload.reason or "arm_sell_only"),
        metadata={"requested_for": str(payload.armed_for_kst_date or ""), "default_for": default_armed_day},
    )
    store.upsert(st)
    _append_event(
        "LIVE_SELL_ONLY_ARM_UPDATED",
        {"actor": user.id, "enabled": bool(st.enabled), "armed_for_kst_date": st.armed_for_kst_date, "scope": st.scope},
    )
    return {"ok": True, "state": asdict(st)}


@router.post("/final-betting/generate")
def generate_final_betting_candidates(
    authorization: str | None = Header(default=None),
    execution_mode: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=5),
) -> dict[str, Any]:
    user = _current_user(authorization)
    _require_live_prep_enabled_for_user(user.id, hint_execution_mode=execution_mode)
    cfg = get_backend_settings()
    svc = get_broker_service()
    out = generate_final_betting_shadow_candidates(
        broker_service=svc,
        backend_settings=cfg,
        user_id=user.id,
        limit=int(limit),
    )
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out)

    st = _store()
    items: list[LiveCandidate] = []
    for row in list(out.get("candidates") or []):
        cand = LiveCandidate(**row)
        st.upsert(cand)
        items.append(cand)

    _append_event(
        "LIVE_PREP_CANDIDATES_GENERATED",
        {"actor": user.id, "strategy_id": "final_betting_v1", "count": len(items)},
    )
    return {"ok": True, "items": [asdict(x) for x in items], "shadow": out.get("shadow") or {}}


@router.post("/hf-shadow/generate")
def generate_hf_shadow(
    strategy_id: str = Query(..., min_length=3, max_length=64),
    authorization: str | None = Header(default=None),
    execution_mode: str | None = Query(default=None),
) -> dict[str, Any]:
    user = _current_user(authorization)
    _require_live_prep_enabled_for_user(user.id, hint_execution_mode=execution_mode)
    cfg = get_backend_settings()
    svc = get_broker_service()
    out = generate_intraday_shadow_report(
        broker_service=svc,
        backend_settings=cfg,
        user_id=user.id,
        strategy_id=strategy_id,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out)
    _append_event(
        "LIVE_PREP_HF_SHADOW_GENERATED",
        {"actor": user.id, "strategy_id": str(strategy_id), "generated_order_count": int(out.get("generated_order_count") or 0)},
    )
    return out


@router.get("/candidates")
def list_candidates(
    authorization: str | None = Header(default=None),
    status_filter: Literal["candidate", "approval_pending", "approved", "submitted", "rejected"] | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    execution_mode: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    user = _current_user(authorization)
    _require_live_prep_enabled_for_user(user.id, hint_execution_mode=execution_mode)
    st = _store()
    items = st.list_filtered(status=status_filter, strategy_id=strategy_id, symbol=symbol, limit=int(limit))
    return {"items": [asdict(x) for x in items], "count": len(items)}


@router.post("/batch-liquidation/prepare")
def prepare_batch_liquidation(
    payload: LiquidationPrepareRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user = _current_user(authorization)
    _require_live_prep_enabled_for_user(user.id, hint_execution_mode=payload.execution_mode)
    cfg = get_backend_settings()
    svc = get_broker_service()
    app_key, app_secret, account_no, product_code, mode = svc.get_plain_credentials(user.id)
    if (mode or "").strip().lower() != "live":
        raise HTTPException(status_code=403, detail="broker_account_not_live")
    tok = svc.ensure_cached_token_for_paper_start(user.id)
    if not tok.ok or not tok.access_token:
        raise HTTPException(status_code=503, detail={"error": tok.failure_code or "token_not_ready", "message": tok.message})
    api_base = svc._resolve_kis_api_base(mode)  # type: ignore[attr-defined]
    client = build_kis_client_for_live_user(
        base_url=api_base,
        access_token=tok.access_token,
        app_key=app_key,
        app_secret=app_secret,
        live_execution_unlocked=False,
    )
    from app.brokers.live_broker import LiveBroker

    broker = LiveBroker(kis_client=client, account_no=account_no, account_product_code=product_code, logger=None)
    positions = broker.get_positions()
    items: list[LiquidationItem] = []
    for p in positions:
        sym = str(getattr(p, "symbol", "") or "")
        q = int(getattr(p, "quantity", 0) or 0)
        if not sym or q <= 0:
            continue
        est = None
        try:
            qt = client.get_quote(sym)
            v = qt.get("stck_prpr") or qt.get("last") or qt.get("price") or qt.get("current_price")
            est = float(v) if v is not None else None
        except Exception:
            est = None
        items.append(LiquidationItem(symbol=sym, quantity=q, price=None if payload.use_market_order else est, est_price=est))

    store = _plan_store()
    plan_id = store.new_id()
    plan = LiquidationPlan(
        plan_id=plan_id,
        user_id=user.id,
        status="prepared",
        scope="account_all",
        use_market_order=bool(payload.use_market_order),
        created_by=str(payload.actor or user.id),
        reason=str(payload.reason or "prepare_liquidation"),
        items=items,
        metadata={"position_count": len(items)},
    )
    store.upsert(plan)
    _append_event(
        "LIVE_PREP_LIQUIDATION_PREPARED",
        {"actor": user.id, "plan_id": plan_id, "item_count": len(items), "use_market_order": bool(payload.use_market_order)},
    )
    return {"ok": True, "plan": asdict(plan)}


@router.get("/batch-liquidation/plans")
def list_liquidation_plans(
    authorization: str | None = Header(default=None),
    execution_mode: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    user = _current_user(authorization)
    _require_live_prep_enabled_for_user(user.id, hint_execution_mode=execution_mode)
    store = _plan_store()
    plans = store.list_by_user(user.id, limit=int(limit))
    return {"ok": True, "plans": [asdict(p) for p in plans], "count": len(plans)}


@router.post("/batch-liquidation/{plan_id}/execute")
def execute_batch_liquidation(
    plan_id: str,
    payload: LiquidationExecuteRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user = _current_user(authorization)
    cfg = get_backend_settings()
    _require_live_prep_enabled_for_user(user.id, hint_execution_mode=payload.execution_mode)
    if (_effective_execution_mode_for_user(user.id, hint_execution_mode=payload.execution_mode) or "").lower() != "live_manual_approval":
        raise HTTPException(status_code=403, detail="EXECUTION_MODE=live_manual_approval 에서만 제출할 수 있습니다.")
    if payload.confirm.strip().upper() != "LIQUIDATE_ALL":
        raise HTTPException(status_code=400, detail="confirm must be LIQUIDATE_ALL")
    live_status = runtime_safety_validation_for_user_id(cfg, user.id)
    if not bool(live_status.get("ok")):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "live_not_ready",
                "blockers": live_status.get("blockers"),
                "blocker_details": live_status.get("blocker_details"),
            },
        )
    if not is_live_order_execution_configured(cfg):
        raise HTTPException(status_code=403, detail="live_execution_not_configured")

    store = _plan_store()
    plan = store.get(plan_id)
    if plan is None or plan.user_id != user.id:
        raise HTTPException(status_code=404, detail="plan_not_found")
    if plan.status != "prepared":
        raise HTTPException(status_code=409, detail=f"plan_not_executable status={plan.status}")

    svc = get_broker_service()
    app_key, app_secret, account_no, product_code, mode = svc.get_plain_credentials(user.id)
    if (mode or "").strip().lower() != "live":
        raise HTTPException(status_code=403, detail="broker_account_not_live")
    tok = svc.ensure_cached_token_for_paper_start(user.id)
    if not tok.ok or not tok.access_token:
        raise HTTPException(status_code=503, detail={"error": tok.failure_code or "token_not_ready", "message": tok.message})
    api_base = svc._resolve_kis_api_base(mode)  # type: ignore[attr-defined]
    client = build_kis_client_for_live_user(
        base_url=api_base,
        access_token=tok.access_token,
        app_key=app_key,
        app_secret=app_secret,
        live_execution_unlocked=True,
    )
    from app.brokers.live_broker import LiveBroker

    broker = LiveBroker(kis_client=client, account_no=account_no, account_product_code=product_code, logger=None)
    open_orders = broker.get_open_orders()
    submitted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for it in list(plan.items or []):
        sym = str(it.symbol or "")
        q = int(it.quantity or 0)
        if not sym or q <= 0:
            continue
        dup = False
        for oo in open_orders:
            if oo.symbol == sym and oo.side == "sell" and int(oo.remaining_quantity) > 0:
                dup = True
                break
        if dup:
            skipped.append({"symbol": sym, "reason": "duplicate_open_order_guard"})
            continue
        order = OrderRequest(
            symbol=sym,
            side="sell",
            quantity=q,
            price=None if bool(plan.use_market_order) else (float(it.price) if it.price is not None else None),
            strategy_id="manual_liquidate_all",
            signal_reason="manual_batch_liquidation",
        )
        res = broker.place_order(order)
        submitted.append({"symbol": sym, "quantity": q, "order_id": res.order_id, "accepted": res.accepted})

    plan.status = "executed"
    plan.executed_at_utc = datetime.now(timezone.utc).isoformat()
    plan.executed_by = str(payload.actor or user.id)
    store.upsert(plan)
    _append_event(
        "LIVE_PREP_LIQUIDATION_EXECUTED",
        {"actor": user.id, "plan_id": plan.plan_id, "submitted": len(submitted), "skipped": len(skipped), "reason": payload.reason},
    )
    return {"ok": True, "plan": asdict(plan), "submitted": submitted, "skipped": skipped}


@router.post("/candidates/{candidate_id}/approve")
def approve_candidate(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user = _current_user(authorization)
    _require_live_prep_enabled_for_user(user.id, hint_execution_mode=payload.execution_mode)
    st = _store()
    cand = st.get(candidate_id)
    if cand is None:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    if cand.status in {"submitted", "rejected"}:
        raise HTTPException(status_code=409, detail=f"cannot_approve_status={cand.status}")
    if cand.status == "approved":
        raise HTTPException(status_code=409, detail="already_approved")
    cand.status = "approved"
    cand.approved_at_utc = datetime.now(timezone.utc).isoformat()
    cand.approved_by = payload.actor or user.id
    st.upsert(cand)
    _append_event(
        "LIVE_PREP_CANDIDATE_APPROVED",
        {"actor": user.id, "candidate_id": cand.candidate_id, "symbol": cand.symbol, "strategy_id": cand.strategy_id, "reason": payload.reason},
    )
    return {"ok": True, "candidate": asdict(cand)}


@router.post("/candidates/{candidate_id}/reject")
def reject_candidate(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user = _current_user(authorization)
    _require_live_prep_enabled_for_user(user.id, hint_execution_mode=payload.execution_mode)
    st = _store()
    cand = st.get(candidate_id)
    if cand is None:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    if cand.status == "submitted":
        raise HTTPException(status_code=409, detail="already_submitted")
    if cand.status == "rejected":
        raise HTTPException(status_code=409, detail="already_rejected")
    cand.status = "rejected"
    cand.rejected_at_utc = datetime.now(timezone.utc).isoformat()
    cand.rejected_by = payload.actor or user.id
    st.upsert(cand)
    _append_event(
        "LIVE_PREP_CANDIDATE_REJECTED",
        {"actor": user.id, "candidate_id": cand.candidate_id, "symbol": cand.symbol, "strategy_id": cand.strategy_id, "reason": payload.reason},
    )
    return {"ok": True, "candidate": asdict(cand)}


def _build_live_snapshot(
    *,
    equity_tracker: EquityTracker,
    cash: float,
    positions: list[Any],
    latest_prices: dict[str, float],
    daily_loss_limit_pct: float,
    max_positions: int,
) -> RiskSnapshot:
    position_values: dict[str, float] = {}
    for p in positions:
        sym = str(getattr(p, "symbol", "") or "")
        q = int(getattr(p, "quantity", 0) or 0)
        if not sym or q <= 0:
            continue
        px = float(latest_prices.get(sym) or 0.0)
        if px <= 0:
            px = float(getattr(p, "average_price", 0.0) or 0.0)
        position_values[sym] = float(px) * float(q)
    equity = float(cash) + sum(position_values.values())
    daily_pct, total_pct = equity_tracker.pnl_snapshot(equity, valid=True)
    rr = RiskRules(RiskLimits(max_positions=max_positions, daily_loss_limit_pct=float(daily_loss_limit_pct)))
    return RiskSnapshot(
        daily_pnl_pct=float(daily_pct),
        total_pnl_pct=float(total_pct),
        equity=float(equity if equity > 0 else 1.0),
        market_filter_ok=True,
        position_values=position_values,
        market_regime="sideways",
        recent_trade_pnls=(),
        consecutive_losses=0,
        latest_entry_score=None,
        todays_new_entries=0,
        trading_cooldown_until=None,
        cooldown_until={},
        equity_basis="live_prep",
        equity_diag={},
        equity_data_ok=True,
    )


@router.post("/candidates/{candidate_id}/submit")
def submit_candidate_order(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user = _current_user(authorization)
    cfg = get_backend_settings()
    _require_live_prep_enabled_for_user(user.id, hint_execution_mode=payload.execution_mode)
    if (_effective_execution_mode_for_user(user.id, hint_execution_mode=payload.execution_mode) or "").lower() != "live_manual_approval":
        raise HTTPException(status_code=403, detail="EXECUTION_MODE=live_manual_approval 에서만 제출할 수 있습니다.")

    live_status = runtime_safety_validation_for_user_id(cfg, user.id)
    if not bool(live_status.get("ok")):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "live_not_ready",
                "blockers": live_status.get("blockers"),
                "blocker_details": live_status.get("blocker_details"),
            },
        )
    if not is_live_order_execution_configured(cfg):
        raise HTTPException(status_code=403, detail="live_execution_not_configured")

    st = _store()
    cand = st.get(candidate_id)
    if cand is None:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    if cand.status != "approved":
        raise HTTPException(status_code=409, detail=f"candidate_not_approved status={cand.status}")
    if cand.submitted_at_utc:
        raise HTTPException(status_code=409, detail="already_submitted")

    svc = get_broker_service()
    app_key, app_secret, account_no, product_code, mode = svc.get_plain_credentials(user.id)
    if (mode or "").strip().lower() != "live":
        raise HTTPException(status_code=403, detail="broker_account_not_live")
    tok = svc.ensure_cached_token_for_paper_start(user.id)
    if not tok.ok or not tok.access_token:
        raise HTTPException(status_code=503, detail={"error": tok.failure_code or "token_not_ready", "message": tok.message})
    api_base = svc._resolve_kis_api_base(mode)  # type: ignore[attr-defined]
    client = build_kis_client_for_live_user(
        base_url=api_base,
        access_token=tok.access_token,
        app_key=app_key,
        app_secret=app_secret,
        live_execution_unlocked=True,
    )

    broker = None
    try:
        from app.brokers.live_broker import LiveBroker

        broker = LiveBroker(kis_client=client, account_no=account_no, account_product_code=product_code, logger=None)
        recent = st.list_filtered(symbol=cand.symbol, limit=500)
        for r in recent:
            if r.candidate_id != cand.candidate_id and r.side == cand.side and r.status == "submitted":
                raise HTTPException(status_code=409, detail="duplicate_submit_guard")

        open_orders = broker.get_open_orders()
        for o in open_orders:
            if o.symbol == cand.symbol and o.side == cand.side and int(o.remaining_quantity) > 0:
                raise HTTPException(status_code=409, detail="duplicate_open_order_guard")

        positions = broker.get_positions()
        cash = float(broker.get_cash() or 0.0)
        latest_prices: dict[str, float] = {}
        for p in positions:
            sym = str(getattr(p, "symbol", "") or "")
            if not sym:
                continue
            try:
                q = client.get_quote(sym)
            except Exception:
                continue
            v = q.get("stck_prpr") or q.get("last") or q.get("price") or q.get("current_price")
            try:
                latest_prices[sym] = float(v)
            except Exception:
                continue

        eq_tracker = EquityTracker(Path(cfg.live_prep_equity_tracker_path))
        snap = _build_live_snapshot(
            equity_tracker=eq_tracker,
            cash=cash,
            positions=positions,
            latest_prices=latest_prices,
            daily_loss_limit_pct=float(cfg.live_prep_daily_loss_limit_pct),
            max_positions=int(cfg.live_prep_max_positions),
        )
        rr = RiskRules(
            RiskLimits(
                max_positions=int(cfg.live_prep_max_positions),
                daily_loss_limit_pct=float(cfg.live_prep_daily_loss_limit_pct),
            )
        )

        order = OrderRequest(
            symbol=cand.symbol,
            side=cand.side,
            quantity=int(cand.quantity),
            price=float(cand.price) if cand.price is not None else None,
            stop_loss_pct=float(cand.stop_loss_pct) if cand.stop_loss_pct is not None else None,
            strategy_id=str(cand.strategy_id),
            signal_reason="live_prep_manual_submit",
        )
        if cand.side == "buy":
            decision = rr.approve_order(order=order, snapshot=snap)
            if not decision.approved:
                cand.touch_error(decision.reason)
                st.upsert(cand)
                _append_event(
                    "LIVE_PREP_SUBMIT_REJECTED_RISK",
                    {
                        "actor": user.id,
                        "candidate_id": cand.candidate_id,
                        "symbol": cand.symbol,
                        "reason": decision.reason,
                        "reason_code": decision.reason_code,
                    },
                )
                raise HTTPException(status_code=403, detail={"error": "risk_rejected", "reason": decision.reason, "code": decision.reason_code})

        if cfg.live_prep_per_order_notional_cap_krw > 0 and order.price is not None:
            notional = float(order.price) * float(order.quantity)
            if notional > float(cfg.live_prep_per_order_notional_cap_krw):
                raise HTTPException(status_code=403, detail="per_order_notional_cap_exceeded")
        if cfg.live_prep_total_notional_cap_krw > 0:
            total_mv = sum(float(v) for v in snap.position_values.values())
            if total_mv > float(cfg.live_prep_total_notional_cap_krw):
                raise HTTPException(status_code=403, detail="total_notional_cap_exceeded")

        res = broker.place_order(order)
    except HTTPException:
        raise
    except Exception as exc:
        cand.touch_error(str(exc))
        st.upsert(cand)
        _append_event(
            "LIVE_PREP_SUBMIT_FAILED",
            {"actor": user.id, "candidate_id": cand.candidate_id, "symbol": cand.symbol, "error": str(exc)[:300]},
        )
        raise HTTPException(status_code=503, detail={"error": "submit_failed", "message": str(exc)}) from exc

    if not res.accepted:
        cand.touch_error(res.message)
        st.upsert(cand)
        _append_event(
            "LIVE_PREP_SUBMIT_REJECTED_BROKER",
            {"actor": user.id, "candidate_id": cand.candidate_id, "symbol": cand.symbol, "message": res.message},
        )
        raise HTTPException(status_code=503, detail={"error": "broker_rejected", "message": res.message})

    cand.status = "submitted"
    cand.submitted_at_utc = datetime.now(timezone.utc).isoformat()
    cand.submitted_by = payload.actor or user.id
    cand.broker_order_id = res.order_id
    st.upsert(cand)
    _append_event(
        "LIVE_PREP_SUBMITTED",
        {
            "actor": user.id,
            "candidate_id": cand.candidate_id,
            "symbol": cand.symbol,
            "strategy_id": cand.strategy_id,
            "broker_order_id": res.order_id,
            "reason": payload.reason,
        },
    )
    return {"ok": True, "candidate": asdict(cand), "broker_result": asdict(res)}

