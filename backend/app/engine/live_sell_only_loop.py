from __future__ import annotations

import logging
import threading
import time as time_mod
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from app.orders.models import OrderRequest
from app.strategy.intraday_common import kst_now, parse_krx_hhmm

from backend.app.api.live_trading_routes import runtime_safety_validation
from backend.app.clients.kis_client import build_kis_client_for_live_user
from backend.app.core.config import BackendSettings, is_live_order_execution_configured
from backend.app.engine.live_prep_engine import compute_final_betting_exit_orders_live
from backend.app.risk.audit import append_risk_event
from backend.app.services.broker_secret_service import BrokerSecretService
from backend.app.services.live_sell_arm_store import SellOnlyArmStore, SellOnlyArmState

logger = logging.getLogger("backend.app.engine.live_sell_only_loop")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _place_live_sell_orders(
    *,
    cfg: BackendSettings,
    broker_service: BrokerSecretService,
    user_id: str,
    orders: list[OrderRequest],
) -> dict[str, Any]:
    if not is_live_order_execution_configured(cfg):
        return {"ok": False, "error": "live_execution_not_configured"}
    safety = runtime_safety_validation()
    if not bool(safety.get("ok")):
        return {"ok": False, "error": "live_not_ready", "blockers": list(safety.get("blockers") or [])}

    app_key, app_secret, account_no, product_code, mode = broker_service.get_plain_credentials(user_id)
    if (mode or "").strip().lower() != "live":
        return {"ok": False, "error": "broker_account_not_live"}
    tok = broker_service.ensure_cached_token_for_paper_start(user_id)
    if not tok.ok or not tok.access_token:
        return {"ok": False, "error": tok.failure_code or "token_not_ready", "message": tok.message}
    api_base = broker_service._resolve_kis_api_base(mode)  # type: ignore[attr-defined]
    client = build_kis_client_for_live_user(
        base_url=api_base,
        access_token=tok.access_token,
        app_key=app_key,
        app_secret=app_secret,
        live_execution_unlocked=True,
    )

    from app.brokers.live_broker import LiveBroker

    broker = LiveBroker(kis_client=client, account_no=account_no, account_product_code=product_code, logger=logger)
    open_orders = broker.get_open_orders()
    submitted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for o in orders:
        if o.side != "sell":
            skipped.append({"symbol": o.symbol, "reason": "non_sell_filtered"})
            continue
        dup = False
        for oo in open_orders:
            if oo.symbol == o.symbol and oo.side == "sell" and int(oo.remaining_quantity) > 0:
                dup = True
                break
        if dup:
            skipped.append({"symbol": o.symbol, "reason": "duplicate_open_order_guard"})
            continue
        res = broker.place_order(o)
        submitted.append({"order": asdict(o), "result": asdict(res)})
    return {"ok": True, "submitted": submitted, "skipped": skipped}


def run_sell_only_tick(
    *,
    cfg: BackendSettings,
    broker_service: BrokerSecretService,
    arm_store: SellOnlyArmStore,
    risk_events_jsonl: str,
) -> dict[str, Any]:
    now = kst_now()
    today = now.strftime("%Y%m%d")
    t0 = parse_krx_hhmm(cfg.live_prep_sell_only_window_start_hhmm)
    t1 = parse_krx_hhmm(cfg.live_prep_sell_only_window_end_hhmm)
    if not (t0 <= now.time() <= t1):
        return {"ok": True, "skipped": "outside_window", "now_kst": now.isoformat()}
    if (cfg.execution_mode or "").strip().lower() != "live_manual_approval":
        return {"ok": True, "skipped": "not_live_manual_approval", "execution_mode": cfg.execution_mode}

    armed = arm_store.list_enabled_for_date(today)
    if not armed:
        return {"ok": True, "skipped": "no_armed_users", "today_kst": today}

    max_orders = int(cfg.live_prep_sell_only_max_orders_per_tick)
    processed: list[dict[str, Any]] = []
    for a in armed:
        user_id = str(a.user_id or "")
        if not user_id:
            continue
        out = compute_final_betting_exit_orders_live(broker_service=broker_service, backend_settings=cfg, user_id=user_id)
        if not out.get("ok"):
            processed.append({"user_id": user_id, "ok": False, "error": out.get("error")})
            continue
        sells = list(out.get("sell_orders") or [])
        orders: list[OrderRequest] = []
        for row in sells:
            try:
                o = OrderRequest(**row)
            except TypeError:
                continue
            if o.side != "sell":
                continue
            if o.quantity <= 0:
                continue
            orders.append(o)
            if len(orders) >= max_orders:
                break
        if not orders:
            processed.append({"user_id": user_id, "ok": True, "submitted": 0})
            continue

        res = _place_live_sell_orders(cfg=cfg, broker_service=broker_service, user_id=user_id, orders=orders)
        processed.append({"user_id": user_id, **res})
        append_risk_event(
            risk_events_jsonl,
            {
                "ts_utc": _utc_now_iso(),
                "event_type": "LIVE_SELL_ONLY_TICK",
                "user_id": user_id,
                "armed_for_kst_date": str(a.armed_for_kst_date),
                "scope": str(a.scope),
                "result": res,
            },
        )

    return {"ok": True, "processed": processed, "today_kst": today, "now_kst": now.isoformat()}


def install_live_sell_only_background(
    settings: BackendSettings,
    broker_service: BrokerSecretService,
) -> None:
    if (settings.trading_mode or "").strip().lower() != "live":
        return
    arm_store = SellOnlyArmStore(settings.live_prep_sell_only_arm_store_json)

    def _loop():
        while True:
            try:
                run_sell_only_tick(
                    cfg=settings,
                    broker_service=broker_service,
                    arm_store=arm_store,
                    risk_events_jsonl=settings.risk_events_jsonl,
                )
            except Exception as exc:
                logger.error("live sell-only loop error: %s", exc)
            time_mod.sleep(float(settings.live_prep_sell_only_tick_interval_sec))

    th = threading.Thread(target=_loop, name="live-sell-only-loop", daemon=True)
    th.start()

