from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="local", alias="APP_ENV")
    app_secret_key: str = Field(default="", alias="APP_SECRET_KEY")
    backend_data_dir: str = Field(default="backend_data", alias="BACKEND_DATA_DIR")
    auth_users_path: str = Field(default="", alias="AUTH_USERS_PATH")
    auth_revoked_tokens_path: str = Field(default="", alias="AUTH_REVOKED_TOKENS_PATH")
    broker_accounts_db_path: str = Field(default="", alias="BROKER_ACCOUNTS_DB_PATH")
    database_url: str = Field(default="sqlite:///./trading.db", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    kis_app_key: str = Field(default="", alias="KIS_APP_KEY")
    kis_app_secret: str = Field(default="", alias="KIS_APP_SECRET")
    kis_base_url: str = Field(default="https://openapi.koreainvestment.com:9443", alias="KIS_BASE_URL")
    kis_mock_base_url: str = Field(default="https://openapivts.koreainvestment.com:29443", alias="KIS_MOCK_BASE_URL")
    trading_mode: str = Field(default="paper", alias="TRADING_MODE")
    execution_mode: str = Field(default="paper_auto", alias="EXECUTION_MODE")
    live_trading: bool = Field(default=False, alias="LIVE_TRADING")
    live_trading_enabled: bool = Field(default=False, alias="LIVE_TRADING_ENABLED")
    live_trading_confirm: bool = Field(default=False, alias="LIVE_TRADING_CONFIRM")
    live_trading_extra_confirm: bool = Field(default=False, alias="LIVE_TRADING_EXTRA_CONFIRM")

    # 실거래 잠금 해제 전 모의(paper) 자동 검증 게이트
    live_unlock_enabled: bool = Field(default=True, alias="LIVE_UNLOCK_ENABLED")
    live_unlock_bypass: bool = Field(default=False, alias="LIVE_UNLOCK_BYPASS")
    live_unlock_lookback_days: int = Field(default=30, ge=7, le=365, alias="LIVE_UNLOCK_LOOKBACK_DAYS")
    live_unlock_min_pnl_samples: int = Field(default=10, ge=3, le=500, alias="LIVE_UNLOCK_MIN_PNL_SAMPLES")
    live_unlock_min_period_return_pct: float = Field(default=0.0, ge=-50.0, le=200.0, alias="LIVE_UNLOCK_MIN_PERIOD_RETURN_PCT")
    live_unlock_max_mdd_pct: float = Field(default=15.0, ge=1.0, le=80.0, alias="LIVE_UNLOCK_MAX_MDD_PCT")
    live_unlock_max_consecutive_loss_days: int = Field(default=5, ge=1, le=60, alias="LIVE_UNLOCK_MAX_CONSECUTIVE_LOSS_DAYS")
    live_unlock_max_order_issue_rate: float = Field(default=0.05, ge=0.0, le=1.0, alias="LIVE_UNLOCK_MAX_ORDER_ISSUE_RATE")
    live_unlock_max_sync_failure_streak: int = Field(default=0, ge=0, le=20, alias="LIVE_UNLOCK_MAX_SYNC_FAILURE_STREAK")

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
    # 스크리너 리스크 게이트 (리스크 최소화: 고변동·갭 과열·유동성 부족 제외)
    screener_max_vol_std_pct: float = Field(default=4.0, ge=0.5, le=20.0, alias="SCREENER_MAX_VOL_STD_PCT")
    screener_max_abs_gap_pct: float = Field(default=5.0, ge=0.5, le=30.0, alias="SCREENER_MAX_ABS_GAP_PCT")
    screener_min_volume_ratio: float = Field(default=1.0, ge=0.5, le=3.0, alias="SCREENER_MIN_VOLUME_RATIO")

    signal_engine_order_quantity: int = Field(default=10, ge=1, alias="SIGNAL_ENGINE_ORDER_QUANTITY")
    signal_suppress_ttl_sec: float = Field(default=120.0, ge=5.0, alias="SIGNAL_SUPPRESS_TTL_SEC")

    risk_order_audit_jsonl: str = Field(default="backend_data/risk/order_audit.jsonl", alias="RISK_ORDER_AUDIT_JSONL")
    risk_events_jsonl: str = Field(default="backend_data/risk/events.jsonl", alias="RISK_EVENTS_JSONL")

    order_tracked_store_json: str = Field(default="backend_data/orders/tracked_orders.json", alias="ORDER_TRACKED_STORE_JSON")
    order_retry_max_attempts: int = Field(default=3, ge=1, le=10, alias="ORDER_RETRY_MAX_ATTEMPTS")
    order_retry_backoff_sec: float = Field(default=0.6, ge=0.1, alias="ORDER_RETRY_BACKOFF_SEC")
    order_stale_submitted_minutes: float = Field(default=180.0, ge=5.0, alias="ORDER_STALE_SUBMITTED_MINUTES")

    live_prep_candidates_store_json: str = Field(
        default="backend_data/live_prep/candidates.json",
        alias="LIVE_PREP_CANDIDATES_STORE_JSON",
    )
    live_prep_equity_tracker_path: str = Field(
        default="backend_data/live_prep/equity_tracker_state.json",
        alias="LIVE_PREP_EQUITY_TRACKER_PATH",
    )
    live_prep_daily_loss_limit_pct: float = Field(
        default=2.0,
        ge=0.1,
        le=20.0,
        alias="LIVE_PREP_DAILY_LOSS_LIMIT_PCT",
    )
    live_prep_total_notional_cap_krw: float = Field(
        default=0.0,
        ge=0.0,
        le=1_000_000_000_000.0,
        alias="LIVE_PREP_TOTAL_NOTIONAL_CAP_KRW",
    )
    live_prep_per_order_notional_cap_krw: float = Field(
        default=0.0,
        ge=0.0,
        le=500_000_000_000.0,
        alias="LIVE_PREP_PER_ORDER_NOTIONAL_CAP_KRW",
    )
    live_prep_max_positions: int = Field(default=6, ge=1, le=50, alias="LIVE_PREP_MAX_POSITIONS")
    live_prep_sell_only_arm_store_json: str = Field(
        default="backend_data/live_prep/sell_only_arm.json",
        alias="LIVE_PREP_SELL_ONLY_ARM_STORE_JSON",
    )
    live_prep_liquidation_plans_store_json: str = Field(
        default="backend_data/live_prep/liquidation_plans.json",
        alias="LIVE_PREP_LIQUIDATION_PLANS_STORE_JSON",
    )
    live_prep_sell_only_tick_interval_sec: float = Field(
        default=15.0,
        ge=2.0,
        le=600.0,
        alias="LIVE_PREP_SELL_ONLY_TICK_INTERVAL_SEC",
    )
    live_prep_sell_only_window_start_hhmm: str = Field(default="090000", alias="LIVE_PREP_SELL_ONLY_WINDOW_START_HHMM")
    live_prep_sell_only_window_end_hhmm: str = Field(default="110000", alias="LIVE_PREP_SELL_ONLY_WINDOW_END_HHMM")
    live_prep_sell_only_max_orders_per_tick: int = Field(default=4, ge=1, le=50, alias="LIVE_PREP_SELL_ONLY_MAX_ORDERS_PER_TICK")

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

    # 성과·FIFO: 체결 행에 수수료/세금이 없을 때 적용하는 비율(소수, 예: 0.0015 = 0.15%)
    kis_buy_fee_rate: float = Field(default=0.00015, ge=0.0, le=0.05, alias="KIS_BUY_FEE_RATE")
    kis_sell_fee_rate: float = Field(default=0.00015, ge=0.0, le=0.05, alias="KIS_SELL_FEE_RATE")
    krx_sell_tax_rate: float = Field(default=0.0015, ge=0.0, le=0.05, alias="KRX_SELL_TAX_RATE")


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


def is_execution_mode_allowed(settings: BackendSettings) -> bool:
    mode = (settings.execution_mode or "").strip().lower()
    tmode = (settings.trading_mode or "").strip().lower()
    if tmode == "paper":
        return mode in {"paper_auto"}
    if tmode == "live":
        return mode in {"live_shadow", "live_manual_approval"}
    return False
