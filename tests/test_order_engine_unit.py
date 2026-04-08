from app.clients.kis_mask import format_masked_payload_json, mask_kis_payload_for_log
from backend.app.orders.order_state_machine import OrderEngineEvent, transition


def test_mask_hides_cano() -> None:
    p = {"CANO": "12345678", "output": {"ODNO": "0001"}}
    m = mask_kis_payload_for_log(p)
    assert m["CANO"] == "***"


def test_transition_risk_to_submitted() -> None:
    assert transition("created", OrderEngineEvent.RISK_APPROVED) == "approved"
    assert transition("approved", OrderEngineEvent.BROKER_ACCEPTED) == "submitted"


def test_masked_json_truncation() -> None:
    s = format_masked_payload_json({"a": 1})
    assert "a" in s
