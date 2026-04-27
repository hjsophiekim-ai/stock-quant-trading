from __future__ import annotations

import json
from pathlib import Path

from app.brokers.paper_broker import PaperBroker
from app.orders.order_manager import OrderManager
from app.risk.rules import RiskRules, RiskSnapshot
from backend.app.core.config import BackendSettings, get_backend_settings
from backend.app.risk.service import install_risk_audit_from_settings


def test_risk_order_audit_is_written_when_signal_evaluated(monkeypatch, tmp_path: Path) -> None:
    audit_p = tmp_path / "risk" / "order_audit.jsonl"
    monkeypatch.setenv("RISK_ORDER_AUDIT_JSONL", str(audit_p))
    get_backend_settings.cache_clear()
    b = BackendSettings()
    install_risk_audit_from_settings(b)

    broker = PaperBroker(initial_cash=1_000_000.0, price_provider=lambda _s: 100.0)
    om = OrderManager(broker=broker, risk_rules=RiskRules())
    snap = RiskSnapshot(
        daily_pnl_pct=0.0,
        total_pnl_pct=0.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
        equity_basis="test",
        equity_diag={},
        equity_data_ok=True,
    )
    sig = type("S", (), {})()
    sig.symbol = "005930"
    sig.side = "buy"
    sig.quantity = 1
    sig.limit_price = 100.0
    sig.stop_loss_pct = 0.8
    sig.strategy_id = "scalp_rsi_flag_hf_v1"
    sig.signal_id = "t1"

    _ = om.evaluate_signal(sig, snap)

    assert audit_p.is_file()
    rows = [json.loads(x) for x in audit_p.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows
    assert rows[-1]["strategy_id"] == "scalp_rsi_flag_hf_v1"
    assert "decision" in rows[-1]

