from backend.app.orders.execution import TrackedExecutionReport, execute_signal_with_kis_engine
from backend.app.orders.order_manager import KisMockExecutionEngine, OrderRetryPolicy, OrderTimeoutPolicy
from backend.app.orders.order_store import TrackedOrderRecord, TrackedOrderStore

__all__ = [
    "KisMockExecutionEngine",
    "OrderRetryPolicy",
    "OrderTimeoutPolicy",
    "TrackedOrderRecord",
    "TrackedOrderStore",
    "TrackedExecutionReport",
    "execute_signal_with_kis_engine",
    "build_kis_mock_execution_engine",
]


def build_kis_mock_execution_engine() -> KisMockExecutionEngine:
    """요청마다 KIS 토큰을 새로 받아 모의 주문 엔진을 구성합니다."""
    import logging

    from app.brokers.kis_paper_broker import KisPaperBroker
    from app.config import get_settings as get_app_settings
    from app.risk.rules import RiskRules
    from backend.app.auth.kis_auth import issue_access_token
    from backend.app.clients.kis_client import build_kis_client_for_backend
    from backend.app.core.config import get_backend_settings, resolved_kis_api_base_url

    bcfg = get_backend_settings()
    acfg = get_app_settings()
    base = resolved_kis_api_base_url(bcfg)
    tr = issue_access_token(
        app_key=bcfg.kis_app_key,
        app_secret=bcfg.kis_app_secret,
        base_url=base,
        timeout_sec=12,
    )
    if not tr.ok or not tr.access_token:
        raise RuntimeError(tr.message or "KIS token failed for order engine")
    client = build_kis_client_for_backend(bcfg, access_token=tr.access_token)
    acct = acfg.resolved_account_no or ""
    prod = acfg.resolved_account_product_code or ""
    if not acct or not prod:
        raise RuntimeError("KIS_ACCOUNT_NO / KIS_ACCOUNT_PRODUCT_CODE required")
    broker = KisPaperBroker(
        kis_client=client,
        account_no=acct,
        account_product_code=prod,
        logger=logging.getLogger("backend.orders"),
    )
    store = TrackedOrderStore(bcfg.order_tracked_store_json)
    return KisMockExecutionEngine(
        broker=broker,
        risk_rules=RiskRules(),
        store=store,
        retry_policy=OrderRetryPolicy(
            max_attempts=bcfg.order_retry_max_attempts,
            backoff_base_sec=bcfg.order_retry_backoff_sec,
        ),
        timeout_policy=OrderTimeoutPolicy(stale_submitted_minutes=bcfg.order_stale_submitted_minutes),
    )
