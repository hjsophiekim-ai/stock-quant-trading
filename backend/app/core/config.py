from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="local", alias="APP_ENV")
    app_secret_key: str = Field(default="", alias="APP_SECRET_KEY")
    database_url: str = Field(default="sqlite:///./trading.db", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    kis_app_key: str = Field(default="", alias="KIS_APP_KEY")
    kis_app_secret: str = Field(default="", alias="KIS_APP_SECRET")
    kis_base_url: str = Field(default="https://openapi.koreainvestment.com:9443", alias="KIS_BASE_URL")
    kis_mock_base_url: str = Field(default="https://openapivts.koreainvestment.com:29443", alias="KIS_MOCK_BASE_URL")
    trading_mode: str = Field(default="paper", alias="TRADING_MODE")
    live_trading: bool = Field(default=False, alias="LIVE_TRADING")
    live_trading_enabled: bool = Field(default=False, alias="LIVE_TRADING_ENABLED")
    live_trading_confirm: bool = Field(default=False, alias="LIVE_TRADING_CONFIRM")
    live_trading_extra_confirm: bool = Field(default=False, alias="LIVE_TRADING_EXTRA_CONFIRM")

    runtime_loop_interval_sec: int = Field(default=120, ge=10, alias="RUNTIME_LOOP_INTERVAL_SEC")
    runtime_max_consecutive_failures: int = Field(default=5, ge=1, alias="RUNTIME_MAX_CONSECUTIVE_FAILURES")
    runtime_state_path: str = Field(default="backend_data/runtime_engine_state.json", alias="RUNTIME_STATE_PATH")
    runtime_error_log_path: str = Field(default="backend_data/runtime_engine_errors.log", alias="RUNTIME_ERROR_LOG_PATH")
    runtime_reports_dir: str = Field(default="backend_data/runtime_reports", alias="RUNTIME_REPORTS_DIR")
    runtime_auto_resume: bool = Field(default=False, alias="RUNTIME_AUTO_RESUME")

    screener_top_n: int = Field(default=20, ge=1, alias="SCREENER_TOP_N")
    screener_top_return_pct: float = Field(default=0.30, ge=0.05, le=0.95, alias="SCREENER_TOP_RETURN_PCT")
    screener_lookback_days: int = Field(default=180, ge=80, alias="SCREENER_LOOKBACK_DAYS")
    screener_report_dir: str = Field(default="backend_data/screening", alias="SCREENER_REPORT_DIR")
    screener_universe_symbols: str = Field(default="", alias="SCREENER_UNIVERSE_SYMBOLS")
    screener_auto_refresh_with_runtime: bool = Field(default=True, alias="SCREENER_AUTO_REFRESH_WITH_RUNTIME")

    signal_engine_order_quantity: int = Field(default=10, ge=1, alias="SIGNAL_ENGINE_ORDER_QUANTITY")
    signal_suppress_ttl_sec: float = Field(default=120.0, ge=5.0, alias="SIGNAL_SUPPRESS_TTL_SEC")

    risk_order_audit_jsonl: str = Field(default="backend_data/risk/order_audit.jsonl", alias="RISK_ORDER_AUDIT_JSONL")
    risk_events_jsonl: str = Field(default="backend_data/risk/events.jsonl", alias="RISK_EVENTS_JSONL")

    order_tracked_store_json: str = Field(default="backend_data/orders/tracked_orders.json", alias="ORDER_TRACKED_STORE_JSON")
    order_retry_max_attempts: int = Field(default=3, ge=1, le=10, alias="ORDER_RETRY_MAX_ATTEMPTS")
    order_retry_backoff_sec: float = Field(default=0.6, ge=0.1, alias="ORDER_RETRY_BACKOFF_SEC")
    order_stale_submitted_minutes: float = Field(default=180.0, ge=5.0, alias="ORDER_STALE_SUBMITTED_MINUTES")

    portfolio_data_dir: str = Field(default="backend_data/portfolio", alias="PORTFOLIO_DATA_DIR")
    portfolio_equity_tracker_path: str = Field(
        default="backend_data/portfolio/equity_tracker_state.json",
        alias="PORTFOLIO_EQUITY_TRACKER_PATH",
    )
    portfolio_sync_interval_sec: int = Field(default=0, ge=0, alias="PORTFOLIO_SYNC_INTERVAL_SEC")
    portfolio_sync_backfill_days: int = Field(default=7, ge=1, le=365, alias="PORTFOLIO_SYNC_BACKFILL_DAYS")
    portfolio_sync_max_consecutive_failures: int = Field(
        default=3, ge=1, le=20, alias="PORTFOLIO_SYNC_MAX_CONSECUTIVE_FAILURES"
    )


@lru_cache(maxsize=1)
def get_backend_settings() -> BackendSettings:
    return BackendSettings()


def resolved_kis_api_base_url(settings: BackendSettings) -> str:
    """TRADING_MODE=paper → 모의 도메인, 그 외 실전 도메인."""
    if (settings.trading_mode or "paper").strip().lower() == "paper":
        return settings.kis_mock_base_url.rstrip("/")
    return settings.kis_base_url.rstrip("/")


def is_live_order_execution_configured(settings: BackendSettings) -> bool:
    live_on = bool(settings.live_trading or settings.live_trading_enabled)
    return (
        settings.trading_mode == "live"
        and live_on
        and settings.live_trading_confirm
        and settings.live_trading_extra_confirm
    )
