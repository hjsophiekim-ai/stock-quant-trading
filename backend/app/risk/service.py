from __future__ import annotations

from typing import Any

from app.risk.audit_hook import register_risk_audit_callback
from app.risk.reason_codes import RiskReasonCode
from app.risk.rules import RiskLimits, RiskRules
from backend.app.core.config import BackendSettings, get_backend_settings
from backend.app.risk.audit import append_order_risk_audit, append_risk_event, read_jsonl_tail


def install_risk_audit_from_settings(settings: BackendSettings | None = None) -> None:
    """FastAPI 기동 시 주문 리스크 감사 JSONL 연결."""
    b = settings or get_backend_settings()

    def _cb(order, snapshot, decision) -> None:
        append_order_risk_audit(b.risk_order_audit_jsonl, order, snapshot, decision)

    register_risk_audit_callback(_cb)


def build_public_risk_status(settings: BackendSettings | None = None) -> dict[str, Any]:
    """대시보드·GET /api/risk/status 용."""
    b = settings or get_backend_settings()
    limits = RiskLimits()
    rules = RiskRules(limits=limits)
    return {
        "reason_codes_enum": [x.value for x in RiskReasonCode],
        "limits": {
            "max_position_weight_pct": limits.max_position_weight * 100,
            "min_position_weight_pct": limits.min_position_weight * 100,
            "bearish_max_position_weight_pct": limits.bearish_max_position_weight * 100,
            "bearish_min_position_weight_pct": limits.bearish_min_position_weight * 100,
            "max_positions": limits.max_positions,
            "bearish_max_positions": limits.bearish_max_positions,
            "daily_loss_halt_pct": limits.daily_loss_limit_pct,
            "total_loss_risk_off_pct": limits.total_loss_limit_pct,
            "reentry_cooldown_minutes": limits.reentry_cooldown_minutes,
            "max_single_order_notional_pct": limits.max_single_order_notional_pct,
            "rolling_loss_window_trades": limits.rolling_loss_window_trades,
            "rolling_loss_limit_pct": limits.rolling_loss_limit_pct,
            "adaptive_loss_streak_threshold": limits.adaptive_loss_streak_threshold,
            "adaptive_position_weight_multiplier": limits.adaptive_position_weight_multiplier,
        },
        "policy_notes": {
            "sells_bypass_daily_total_halt": True,
            "cycle_abort_only_on": RiskReasonCode.SYSTEM_OFF_TOTAL_LOSS.value,
            "high_vol_blocks_new_buys": limits.high_vol_new_entry_blocked,
        },
        "recent_order_audits": read_jsonl_tail(b.risk_order_audit_jsonl, max_lines=40),
        "recent_events": read_jsonl_tail(b.risk_events_jsonl, max_lines=40),
    }
