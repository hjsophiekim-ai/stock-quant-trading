export type TradingBadge = "test" | "live";

export interface LiveTradingStatusResponse {
  trading_mode: "paper" | "live";
  live_trading_flag: boolean;
  secondary_confirm_flag: boolean;
  extra_approval_flag: boolean;
  can_place_live_order: boolean;
  trading_badge: TradingBadge;
  warning_message: string;
}

export interface LiveTradingSettingsUpdateRequest {
  live_trading_flag: boolean;
  secondary_confirm_flag: boolean;
  extra_approval_flag: boolean;
  reason: string;
}

export interface KillSwitchStatusResponse {
  kill_switch_state: "NORMAL" | "TRIGGERED" | "COOLDOWN";
  daily_loss_pct: number;
  total_loss_pct: number;
  daily_loss_limit_pct: number;
  total_loss_limit_pct: number;
  loss_limit_exceeded: boolean;
}

export interface LiveSafetyHistoryItem {
  ts: string;
  actor: string;
  action: string;
  reason: string;
}
