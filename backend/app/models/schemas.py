from pydantic import BaseModel


class RuntimeSafetyStatus(BaseModel):
    trading_mode: str
    live_trading: bool
    live_trading_confirm: bool
    can_place_live_order: bool
