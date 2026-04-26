export type TradingMode = "paper" | "live";

export type ExecutionMode = "paper_auto" | "live_shadow" | "live_manual_approval";

export interface TradingModeResponse {
  default_mode: TradingMode;
  live_status: "locked" | "enabled";
}

export interface RecentTradeItem {
  trade_id: string;
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  filled_at: string;
  status: "filled" | "cancelled" | "rejected";
}

export interface RecentTradesResponse {
  items: RecentTradeItem[];
}

export interface StartPaperTradingRequest {
  strategy_id: string;
}

export interface PaperTradingStatusResponse {
  mode: "paper";
  status: "running" | "stopped" | "risk-off";
  strategy_id: string | null;
  started_at: string | null;
  last_heartbeat_at: string | null;
}

export interface PaperTradingPositionItem {
  symbol: string;
  quantity: number;
  average_price: number;
}

export interface PaperTradingPositionsResponse {
  items: PaperTradingPositionItem[];
}

export interface PaperPnlPoint {
  ts: string;
  return_pct: number;
}

export interface PaperTradingPnlResponse {
  today_return_pct: number;
  monthly_return_pct: number;
  cumulative_return_pct: number;
  realized_pnl: number;
  unrealized_pnl: number;
  chart: PaperPnlPoint[];
}

export interface PaperTradingLogItem {
  ts: string;
  level: "info" | "warning" | "error";
  message: string;
}

export interface PaperTradingLogsResponse {
  items: PaperTradingLogItem[];
}

export interface LiveTradingSettingsUpdateRequest {
  live_trading_flag: boolean;
  secondary_confirm_flag: boolean;
  extra_approval_flag: boolean;
  reason: string;
  actor?: string;
}

export interface LiveTradingStatusResponse {
  trading_mode: TradingMode;
  execution_mode?: ExecutionMode;
  live_trading_flag: boolean;
  secondary_confirm_flag: boolean;
  extra_approval_flag: boolean;
  live_emergency_stop?: boolean;
  can_place_live_order: boolean;
  trading_badge: "test" | "live";
  warning_message: string;
}

export interface RuntimeSafetyValidationResponse {
  ok: boolean;
  blockers: string[];
}

export interface KillSwitchStatusResponse {
  kill_switch_state: "NORMAL" | "TRIGGERED" | "COOLDOWN";
  daily_loss_pct: number;
  total_loss_pct: number;
  daily_loss_limit_pct: number;
  total_loss_limit_pct: number;
  loss_limit_exceeded: boolean;
  message: string;
}
