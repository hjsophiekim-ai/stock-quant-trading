from functools import lru_cache

from pydantic import Field
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

    daily_loss_limit_pct: float = Field(default=2.0, alias="DAILY_LOSS_LIMIT_PCT")
    total_loss_limit_pct: float = Field(default=10.0, alias="TOTAL_LOSS_LIMIT_PCT")
    default_stop_loss_pct: float = Field(default=3.0, alias="DEFAULT_STOP_LOSS_PCT")

    @property
    def resolved_account_no(self) -> str:
        return self.kis_account_no or self.account_number

    @property
    def resolved_account_product_code(self) -> str:
        return self.kis_account_product_code or self.account_product_code

    @property
    def resolved_live_trading_enabled(self) -> bool:
        return bool(self.live_trading or self.live_trading_enabled)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
