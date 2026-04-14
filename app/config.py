import json
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

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
    paper_trading_interval_sec: int = Field(default=600, ge=30, alias="PAPER_TRADING_INTERVAL_SEC")
    paper_trading_symbols: str = Field(default="005930,000660", alias="PAPER_TRADING_SYMBOLS")
    # 비어 있으면 paper_trading_symbols(또는 종목 수 부족 시 data/domestic_liquid_symbols 상위 N) 사용 — 인트라데이 전용
    paper_intraday_symbols: str = Field(default="", alias="PAPER_INTRADAY_SYMBOLS")
    paper_session_state_path: str = Field(default="data/paper_trading_session.json", alias="PAPER_SESSION_STATE_PATH")
    paper_session_auto_resume: bool = Field(default=True, alias="PAPER_SESSION_AUTO_RESUME")
    paper_kis_chart_lookback_days: int = Field(default=60, ge=20, alias="PAPER_KIS_CHART_LOOKBACK_DAYS")
    paper_smoke_mode: bool = Field(default=False, alias="PAPER_SMOKE_MODE")
    paper_kis_universe_cache_ttl_sec: int = Field(
        default=300,
        ge=0,
        validation_alias=AliasChoices(
            "PAPER_KIS_UNIVERSE_CACHE_TTL_SEC",
            "PAPER_UNIVERSE_CACHE_TTL_SEC",
        ),
    )
    paper_kis_kospi_cache_ttl_sec: int = Field(
        default=300,
        ge=0,
        validation_alias=AliasChoices(
            "PAPER_KIS_KOSPI_CACHE_TTL_SEC",
            "PAPER_KOSPI_CACHE_TTL_SEC",
        ),
    )
    paper_positions_refresh_interval_sec: int = Field(
        default=900,
        ge=0,
        alias="PAPER_POSITIONS_REFRESH_INTERVAL_SEC",
    )
    paper_portfolio_sync_interval_sec: int = Field(
        default=1800,
        ge=0,
        alias="PAPER_PORTFOLIO_SYNC_INTERVAL_SEC",
    )

    # KISClient rate-limit / throttle (백엔드 Paper 경로가 app Settings 를 읽음)
    kis_min_request_interval_ms: int = Field(default=250, ge=0, alias="KIS_MIN_REQUEST_INTERVAL_MS")
    kis_rate_limit_max_retries: int = Field(default=6, ge=0, alias="KIS_RATE_LIMIT_MAX_RETRIES")
    kis_rate_limit_backoff_base_sec: float = Field(default=0.5, ge=0.0, alias="KIS_RATE_LIMIT_BACKOFF_BASE_SEC")
    kis_rate_limit_backoff_cap_sec: float = Field(default=30.0, ge=0.0, alias="KIS_RATE_LIMIT_BACKOFF_CAP_SEC")

    # Paper 인트라데이(분봉 단타) — 스윙 일봉 루프와 독립. 목표 빈도는 상한·설명용이며 거래를 보장하지 않음.
    paper_intraday_enabled: bool = Field(default=False, alias="PAPER_INTRADAY_ENABLED")
    paper_intraday_bar_minutes: int = Field(default=3, ge=1, le=60, alias="PAPER_INTRADAY_BAR_MINUTES")
    paper_intraday_loop_interval_sec: int = Field(default=90, ge=20, alias="PAPER_INTRADAY_LOOP_INTERVAL_SEC")
    paper_intraday_max_trades_per_day: int = Field(default=24, ge=0, alias="PAPER_INTRADAY_MAX_TRADES_PER_DAY")
    paper_intraday_max_open_positions: int = Field(default=3, ge=1, alias="PAPER_INTRADAY_MAX_OPEN_POSITIONS")
    paper_intraday_max_hold_minutes: int = Field(default=20, ge=1, alias="PAPER_INTRADAY_MAX_HOLD_MINUTES")
    paper_intraday_stop_loss_pct: float = Field(default=0.65, ge=0.05, le=20.0, alias="PAPER_INTRADAY_STOP_LOSS_PCT")
    paper_intraday_take_profit_pct: float = Field(default=1.1, ge=0.05, le=50.0, alias="PAPER_INTRADAY_TAKE_PROFIT_PCT")
    paper_intraday_trailing_stop_pct: float = Field(default=0.45, ge=0.0, le=20.0, alias="PAPER_INTRADAY_TRAILING_STOP_PCT")
    paper_intraday_cooldown_minutes: int = Field(default=12, ge=0, alias="PAPER_INTRADAY_COOLDOWN_MINUTES")
    paper_intraday_min_quote_volume: float = Field(
        default=80_000.0,
        ge=0.0,
        alias="PAPER_INTRADAY_MIN_QUOTE_VOLUME",
    )
    paper_intraday_min_trade_value_krw: float = Field(
        default=3_000_000_000.0,
        ge=0.0,
        alias="PAPER_INTRADAY_MIN_TRADE_VALUE_KRW",
    )
    paper_intraday_max_spread_pct: float = Field(default=0.35, ge=0.0, alias="PAPER_INTRADAY_MAX_SPREAD_PCT")
    paper_intraday_max_chase_candle_pct: float = Field(default=1.8, ge=0.0, alias="PAPER_INTRADAY_MAX_CHASE_CANDLE_PCT")
    paper_intraday_max_daily_loss_pct: float = Field(default=1.5, ge=0.0, alias="PAPER_INTRADAY_MAX_DAILY_LOSS_PCT")
    paper_intraday_flatten_before_close_minutes: int = Field(
        default=15,
        ge=1,
        alias="PAPER_INTRADAY_FLATTEN_BEFORE_CLOSE_MINUTES",
    )
    paper_intraday_target_round_trip_trades: int = Field(
        default=10,
        ge=0,
        alias="PAPER_INTRADAY_TARGET_ROUND_TRIP_TRADES",
    )
    paper_intraday_chart_cache_ttl_sec: float = Field(default=45.0, ge=0.0, alias="PAPER_INTRADAY_CHART_CACHE_TTL_SEC")
    paper_intraday_chart_min_interval_sec: float = Field(
        default=0.35,
        ge=0.0,
        alias="PAPER_INTRADAY_CHART_MIN_INTERVAL_SEC",
    )
    paper_intraday_order_quantity: int = Field(default=1, ge=1, alias="PAPER_INTRADAY_ORDER_QUANTITY")
    paper_intraday_duplicate_order_guard_sec: float = Field(
        default=45.0,
        ge=0.0,
        alias="PAPER_INTRADAY_DUPLICATE_ORDER_GUARD_SEC",
    )

    # Dynamic position sizing controls.
    sizing_bullish_boost_multiplier: float = Field(default=1.20, alias="SIZING_BULLISH_BOOST_MULTIPLIER")
    sizing_bearish_cut_multiplier: float = Field(default=0.60, alias="SIZING_BEARISH_CUT_MULTIPLIER")
    sizing_sideways_cut_multiplier: float = Field(default=0.80, alias="SIZING_SIDEWAYS_CUT_MULTIPLIER")
    sizing_high_volatility_cut_multiplier: float = Field(default=0.00, alias="SIZING_HIGH_VOLATILITY_CUT_MULTIPLIER")
    sizing_high_vol_atr_threshold_pct: float = Field(default=4.0, alias="SIZING_HIGH_VOL_ATR_THRESHOLD_PCT")
    sizing_low_vol_atr_threshold_pct: float = Field(default=1.8, alias="SIZING_LOW_VOL_ATR_THRESHOLD_PCT")
    sizing_losing_streak_deleverage_step: float = Field(default=0.10, alias="SIZING_LOSING_STREAK_DELEVERAGE_STEP")
    sizing_max_deleverage_multiplier: float = Field(default=0.50, alias="SIZING_MAX_DELEVERAGE_MULTIPLIER")

    def load_intraday_fallback_symbols(self, *, max_count: int = 25) -> list[str]:
        """국내 유동성 JSON 상위 종목(인트라데이 기본 폭 확대용)."""
        root = Path(__file__).resolve().parent.parent
        p = root / "data" / "domestic_liquid_symbols.json"
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return []
            out: list[str] = []
            for row in raw:
                if isinstance(row, dict) and row.get("symbol"):
                    out.append(str(row["symbol"]).strip())
                if len(out) >= max_count:
                    break
            return out
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []

    def resolved_intraday_symbol_list(self) -> list[str]:
        """
        PAPER_INTRADAY_SYMBOLS 가 있으면 우선.
        없으면 PAPER_TRADING_SYMBOLS — 종목이 10개 미만이면 domestic_liquid 상위와 병합(최대 ~30).
        """
        explicit = (self.paper_intraday_symbols or "").strip()
        if explicit:
            return [x.strip() for x in explicit.split(",") if x.strip()][:60]
        base = [x.strip() for x in (self.paper_trading_symbols or "").split(",") if x.strip()]
        if len(base) >= 10:
            return base[:35]
        fb = self.load_intraday_fallback_symbols(max_count=28)
        merged: list[str] = []
        seen: set[str] = set()
        for s in base + fb:
            s = s.strip()
            if not s or s in seen:
                continue
            seen.add(s)
            merged.append(s)
            if len(merged) >= 30:
                break
        return merged

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
