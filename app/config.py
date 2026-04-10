from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    kis_app_key: str = Field(default="", alias="KIS_APP_KEY")
    kis_app_secret: str = Field(default="", alias="KIS_APP_SECRET")
    kis_base_url: str = Field(default="https://openapi.koreainvestment.com:9443", alias="KIS_BASE_URL")
    kis_mock_base_url: str = Field(default="https://openapivts.koreainvestment.com:29443", alias="KIS_MOCK_BASE_URL")

    # Prefer KIS_* names, keep backward compatibility with legacy ACCOUNT_* keys.
    kis_account_no: str = Field(default="", alias="KIS_ACCOUNT_NO")
    kis_account_product_code: str = Field(default="", alias="KIS_ACCOUNT_PRODUCT_CODE")
    account_number: str = Field(default="", alias="ACCOUNT_NUMBER")
    account_product_code: str = Field(default="", alias="ACCOUNT_PRODUCT_CODE")

    trading_mode: str = Field(default="paper", alias="TRADING_MODE")
    # Prefer LIVE_TRADING, keep backward compatibility with LIVE_TRADING_ENABLED.
    live_trading: bool = Field(default=False, alias="LIVE_TRADING")
    live_trading_enabled: bool = Field(default=False, alias="LIVE_TRADING_ENABLED")
    live_trading_confirm: bool = Field(default=False, alias="LIVE_TRADING_CONFIRM")
    live_trading_extra_confirm: bool = Field(default=False, alias="LIVE_TRADING_EXTRA_CONFIRM")
    live_order_dry_run_log: bool = Field(default=True, alias="LIVE_ORDER_DRY_RUN_LOG")

    daily_loss_limit_pct: float = Field(default=2.0, alias="DAILY_LOSS_LIMIT_PCT")
    total_loss_limit_pct: float = Field(default=10.0, alias="TOTAL_LOSS_LIMIT_PCT")
    default_stop_loss_pct: float = Field(default=3.0, alias="DEFAULT_STOP_LOSS_PCT")

    # KIS 모의투자 자동 paper trading (실주문 경로와 분리; openapivts 전용 브로커 사용)
    paper_use_kis_execution: bool = Field(default=False, alias="PAPER_USE_KIS_EXECUTION")
    paper_trading_loop: bool = Field(default=False, alias="PAPER_TRADING_LOOP")
    # 백엔드 Paper 세션 스레드 틱 간격 — KIS mock rate limit(EGW00201) 완화용 기본 600초.
    paper_trading_interval_sec: int = Field(default=600, ge=30, alias="PAPER_TRADING_INTERVAL_SEC")
    # 모의 API rate limit 완화: 기본 2종목·짧은 룩백. 쉼표로 복수 지정.
    paper_trading_symbols: str = Field(default="005930,000660", alias="PAPER_TRADING_SYMBOLS")
    paper_session_state_path: str = Field(default="data/paper_trading_session.json", alias="PAPER_SESSION_STATE_PATH")
    # 차트·유니버스 룩백(일) — KIS mock 호출량에 비례하므로 기본 60.
    paper_kis_chart_lookback_days: int = Field(default=60, ge=20, alias="PAPER_KIS_CHART_LOOKBACK_DAYS")
    # True면 1종목·룩백 상한 60일로 자동 축소 (스모크/저부하)
    paper_smoke_mode: bool = Field(default=False, alias="PAPER_SMOKE_MODE")
    paper_kis_universe_cache_ttl_sec: int = Field(
        default=300,
        ge=0,
        validation_alias=AliasChoices("PAPER_UNIVERSE_CACHE_TTL_SEC", "PAPER_KIS_UNIVERSE_CACHE_TTL_SEC"),
    )
    paper_kis_kospi_cache_ttl_sec: int = Field(
        default=300,
        ge=0,
        validation_alias=AliasChoices("PAPER_KOSPI_CACHE_TTL_SEC", "PAPER_KIS_KOSPI_CACHE_TTL_SEC"),
    )
    # 0이면 매 틱 포지션 스냅샷(호출 많음). KIS mock 부하 완화용 기본 900초.
    paper_positions_refresh_interval_sec: int = Field(
        default=900,
        ge=0,
        alias="PAPER_POSITIONS_REFRESH_INTERVAL_SEC",
    )
    # 0이면 portfolio sync 비활성. 기본 1800초(30분).
    paper_portfolio_sync_interval_sec: int = Field(
        default=1800,
        ge=0,
        alias="PAPER_PORTFOLIO_SYNC_INTERVAL_SEC",
    )

    kis_min_request_interval_ms: int = Field(default=280, ge=0, le=10_000, alias="KIS_MIN_REQUEST_INTERVAL_MS")
    kis_rate_limit_max_retries: int = Field(default=8, ge=0, le=30, alias="KIS_RATE_LIMIT_MAX_RETRIES")
    kis_rate_limit_backoff_base_sec: float = Field(default=0.55, ge=0.05, le=30.0, alias="KIS_RATE_LIMIT_BACKOFF_BASE_SEC")
    kis_rate_limit_backoff_cap_sec: float = Field(default=32.0, ge=1.0, le=120.0, alias="KIS_RATE_LIMIT_BACKOFF_CAP_SEC")

    # Dynamic position sizing controls.
    sizing_bullish_boost_multiplier: float = Field(default=1.20, alias="SIZING_BULLISH_BOOST_MULTIPLIER")
    sizing_bearish_cut_multiplier: float = Field(default=0.60, alias="SIZING_BEARISH_CUT_MULTIPLIER")
    sizing_sideways_cut_multiplier: float = Field(default=0.80, alias="SIZING_SIDEWAYS_CUT_MULTIPLIER")
    sizing_high_volatility_cut_multiplier: float = Field(default=0.00, alias="SIZING_HIGH_VOLATILITY_CUT_MULTIPLIER")
    sizing_high_vol_atr_threshold_pct: float = Field(default=4.0, alias="SIZING_HIGH_VOL_ATR_THRESHOLD_PCT")
    sizing_low_vol_atr_threshold_pct: float = Field(default=1.8, alias="SIZING_LOW_VOL_ATR_THRESHOLD_PCT")
    sizing_losing_streak_deleverage_step: float = Field(default=0.10, alias="SIZING_LOSING_STREAK_DELEVERAGE_STEP")
    sizing_max_deleverage_multiplier: float = Field(default=0.50, alias="SIZING_MAX_DELEVERAGE_MULTIPLIER")

    @property
    def resolved_account_no(self) -> str:
        return self.kis_account_no or self.account_number

    @property
    def resolved_account_product_code(self) -> str:
        return self.kis_account_product_code or self.account_product_code

    @property
    def resolved_live_trading_enabled(self) -> bool:
        return bool(self.live_trading or self.live_trading_enabled)

    @property
    def is_live_order_allowed(self) -> bool:
        # Require explicit dual-confirmation to reduce accidental live order risk.
        return (
            self.resolved_live_trading_enabled
            and self.live_trading_confirm
            and self.live_trading_extra_confirm
            and self.trading_mode == "live"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
