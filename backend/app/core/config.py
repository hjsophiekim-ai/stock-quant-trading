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
    trading_mode: str = Field(default="paper", alias="TRADING_MODE")
    live_trading: bool = Field(default=False, alias="LIVE_TRADING")
    live_trading_confirm: bool = Field(default=False, alias="LIVE_TRADING_CONFIRM")


@lru_cache(maxsize=1)
def get_backend_settings() -> BackendSettings:
    return BackendSettings()
