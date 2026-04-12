from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TradingMode = Literal["paper", "live"]
ConnectionStatus = Literal["unknown", "success", "failed"]


class BrokerAccountUpsertRequest(BaseModel):
    kis_app_key: str = Field(min_length=8, max_length=256)
    kis_app_secret: str = Field(min_length=8, max_length=256)
    kis_account_no: str = Field(min_length=4, max_length=32)
    kis_account_product_code: str = Field(min_length=1, max_length=8)
    trading_mode: TradingMode = "paper"


class BrokerAccountResponse(BaseModel):
    id: str
    user_id: str
    kis_app_key_masked: str
    kis_account_no_masked: str
    kis_account_product_code: str
    trading_mode: TradingMode
    connection_status: ConnectionStatus
    connection_message: str | None = None
    last_tested_at: datetime | None = None
    updated_at: datetime
    created_at: datetime


class BrokerConnectionTestResponse(BaseModel):
    ok: bool
    status: ConnectionStatus
    message: str
    balance_check_ok: bool | None = None
    balance_rt_cd: str | None = None
    balance_cash_hint: str | None = None
