import json
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
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
    # 비어 있으면 인트라데이 전용 기본 대표 유동 종목 fallback 사용
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
    paper_intraday_max_trades_per_day: int = Field(default=30, ge=0, alias="PAPER_INTRADAY_MAX_TRADES_PER_DAY")
    paper_intraday_max_open_positions: int = Field(default=3, ge=1, alias="PAPER_INTRADAY_MAX_OPEN_POSITIONS")
    paper_intraday_max_hold_minutes: int = Field(default=20, ge=1, alias="PAPER_INTRADAY_MAX_HOLD_MINUTES")
    paper_intraday_stop_loss_pct: float = Field(default=0.50, ge=0.05, le=20.0, alias="PAPER_INTRADAY_STOP_LOSS_PCT")
    paper_intraday_take_profit_pct: float = Field(default=0.80, ge=0.05, le=50.0, alias="PAPER_INTRADAY_TAKE_PROFIT_PCT")
    paper_intraday_trailing_stop_pct: float = Field(default=0.35, ge=0.0, le=20.0, alias="PAPER_INTRADAY_TRAILING_STOP_PCT")
    paper_intraday_cooldown_minutes: int = Field(default=7, ge=0, alias="PAPER_INTRADAY_COOLDOWN_MINUTES")
    paper_intraday_min_quote_volume: float = Field(
        default=50_000.0,
        ge=0.0,
        alias="PAPER_INTRADAY_MIN_QUOTE_VOLUME",
    )
    paper_intraday_min_trade_value_krw: float = Field(
        default=1_500_000_000.0,
        ge=0.0,
        alias="PAPER_INTRADAY_MIN_TRADE_VALUE_KRW",
    )
    paper_intraday_max_spread_pct: float = Field(default=0.45, ge=0.0, alias="PAPER_INTRADAY_MAX_SPREAD_PCT")
    paper_intraday_max_chase_candle_pct: float = Field(default=1.8, ge=0.0, alias="PAPER_INTRADAY_MAX_CHASE_CANDLE_PCT")
    paper_intraday_max_daily_loss_pct: float = Field(default=1.2, ge=0.0, alias="PAPER_INTRADAY_MAX_DAILY_LOSS_PCT")
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
    paper_multi_strategy_mode: bool = Field(
        default=False,
        alias="PAPER_MULTI_STRATEGY_MODE",
        description="멀티 전략(스윙+인트라데이) 병렬 틱. false면 기존 단일 전략 경로 유지.",
    )
    paper_multi_swing_strategy_id: str = Field(
        default="swing_relaxed_v1",
        alias="PAPER_MULTI_SWING_STRATEGY_ID",
        description="멀티 모드 일봉 스윙 레그 strategy_id (paper_strategy 매핑).",
    )
    paper_swing_capital_pct: float = Field(
        default=60.0,
        ge=0.0,
        le=100.0,
        alias="PAPER_SWING_CAPITAL_PCT",
        description="평가금 대비 스윙 레그 노셔널 가이드(%).",
    )
    paper_intraday_capital_pct: float = Field(
        default=40.0,
        ge=0.0,
        le=100.0,
        alias="PAPER_INTRADAY_CAPITAL_PCT",
        description="평가금 대비 인트라데이 레그 노셔널 가이드(%).",
    )
    paper_max_capital_per_position_pct: float = Field(
        default=8.0,
        ge=0.01,
        le=100.0,
        alias="PAPER_MAX_CAPITAL_PER_POSITION_PCT",
        description="인트라데이 버킷 내 단일 종목 최대 투입(%).",
    )
    paper_risk_per_trade_pct: float = Field(
        default=0.45,
        ge=0.01,
        le=10.0,
        alias="PAPER_RISK_PER_TRADE_PCT",
        description="평가금 대비 1회 허용 손실(%); 손절폭으로 수량 역산.",
    )
    paper_intraday_risk_based_quantity: bool = Field(
        default=False,
        alias="PAPER_INTRADAY_RISK_BASED_QUANTITY",
        description="멀티 없이도 스캘프 매수 수량을 리스크 기반으로.",
    )
    paper_multi_router_prefer_scalp_on_overlap: bool = Field(
        default=True,
        alias="PAPER_MULTI_ROUTER_PREFER_SCALP_ON_OVERLAP",
        description="스윙·인트라데이 후보 교집합 시 스캘프 우선 배정.",
    )
    paper_intraday_duplicate_order_guard_sec: float = Field(
        default=45.0,
        ge=0.0,
        alias="PAPER_INTRADAY_DUPLICATE_ORDER_GUARD_SEC",
    )

    # KRX 세션(장전/정규/장후) — Paper 인트라데이 분봉·주문 게이트
    paper_krx_preopen_enabled: bool = Field(default=False, alias="PAPER_KRX_PREOPEN_ENABLED")
    paper_krx_afterhours_enabled: bool = Field(default=False, alias="PAPER_KRX_AFTERHOURS_ENABLED")
    paper_krx_preopen_start_hhmm: str = Field(default="080000", alias="PAPER_KRX_PREOPEN_START_HHMM")
    paper_krx_regular_open_hhmm: str = Field(default="090000", alias="PAPER_KRX_REGULAR_OPEN_HHMM")
    paper_krx_regular_close_hhmm: str = Field(default="153000", alias="PAPER_KRX_REGULAR_CLOSE_HHMM")
    paper_krx_afterhours_close_hhmm: str = Field(default="180000", alias="PAPER_KRX_AFTERHOURS_CLOSE_HHMM")
    paper_krx_extended_fetch_enabled: bool = Field(default=False, alias="PAPER_KRX_EXTENDED_FETCH_ENABLED")
    paper_krx_extended_order_enabled: bool = Field(default=False, alias="PAPER_KRX_EXTENDED_ORDER_ENABLED")

    # 장전/장후 유동성 필터 보수화(배수)
    paper_intraday_preopen_min_vol_mult: float = Field(default=1.15, ge=0.1, alias="PAPER_INTRADAY_PREOPEN_MIN_VOL_MULT")
    paper_intraday_preopen_spread_mult: float = Field(default=0.88, ge=0.05, le=2.0, alias="PAPER_INTRADAY_PREOPEN_SPREAD_MULT")
    paper_intraday_preopen_chase_mult: float = Field(default=0.82, ge=0.05, le=2.0, alias="PAPER_INTRADAY_PREOPEN_CHASE_MULT")
    paper_intraday_afterhours_min_vol_mult: float = Field(default=1.35, ge=0.1, alias="PAPER_INTRADAY_AFTERHOURS_MIN_VOL_MULT")
    paper_intraday_afterhours_spread_mult: float = Field(default=0.65, ge=0.05, le=2.0, alias="PAPER_INTRADAY_AFTERHOURS_SPREAD_MULT")
    paper_intraday_afterhours_chase_mult: float = Field(default=0.72, ge=0.05, le=2.0, alias="PAPER_INTRADAY_AFTERHOURS_CHASE_MULT")

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

    def intraday_fallback_symbols(self) -> list[str]:
        """인트라데이 기본 대표 유동 종목(코스피/코스닥 대형·고유동 중심)."""
        return [
            "005930",  # 삼성전자
            "000660",  # SK하이닉스
            "035420",  # NAVER
            "035720",  # 카카오
            "005380",  # 현대차
            "000270",  # 기아
            "207940",  # 삼성바이오로직스
            "068270",  # 셀트리온
            "105560",  # KB금융
            "055550",  # 신한지주
            "005490",  # POSCO홀딩스
            "373220",  # LG에너지솔루션
            "006400",  # 삼성SDI
            "051910",  # LG화학
            "012450",  # 한화에어로스페이스
            "034020",  # 두산에너빌리티
            "329180",  # HD현대중공업
            "015760",  # 한국전력
            "003490",  # 대한항공
            "011200",  # HMM
            "096770",  # SK이노베이션
            "028260",  # 삼성물산
            "012330",  # 현대모비스
            "005935",  # 삼성전자우
            "323410",  # 카카오뱅크
        ]

    def resolved_intraday_symbol_list(self) -> list[str]:
        """
        PAPER_INTRADAY_SYMBOLS 가 있으면 우선.
        비어 있으면 인트라데이 전용 fallback(20~30개) 사용.
        """
        explicit = (self.paper_intraday_symbols or "").strip()
        if explicit:
            return [x.strip() for x in explicit.split(",") if x.strip()][:60]
        return self.intraday_fallback_symbols()

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

    @property
    def paper_uses_intraday_risk_sized_quantity(self) -> bool:
        return bool(self.paper_multi_strategy_mode or self.paper_intraday_risk_based_quantity)

    @model_validator(mode="after")
    def _validate_capital_split(self) -> "Settings":
        if float(self.paper_swing_capital_pct) + float(self.paper_intraday_capital_pct) > 100.01:
            raise ValueError("PAPER_SWING_CAPITAL_PCT + PAPER_INTRADAY_CAPITAL_PCT must be <= 100")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
