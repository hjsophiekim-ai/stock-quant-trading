export type TradingBadge = "test" | "live";

export interface LiveTradingStatusResponse {
  trading_mode: "paper" | "live";
  execution_mode?: "paper_auto" | "live_shadow" | "live_manual_approval";
  live_trading_flag: boolean;
  secondary_confirm_flag: boolean;
  extra_approval_flag: boolean;
  requested_live_trading_flag?: boolean;
  requested_secondary_confirm_flag?: boolean;
  requested_extra_approval_flag?: boolean;
  live_emergency_stop?: boolean;
  paper_readiness_ok?: boolean;
  can_place_live_order: boolean;
  effective_can_place_live_order?: boolean;
  unlock_pending_due_to_paper_readiness?: boolean;
  settings_saved_but_not_effective?: boolean;
  pending_blockers?: string[];
  pending_blocker_details?: Array<{ code: string; message: string }>;
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
