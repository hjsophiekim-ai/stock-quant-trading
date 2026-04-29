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
  requested_live_trading_flag?: boolean;
  requested_secondary_confirm_flag?: boolean;
  requested_extra_approval_flag?: boolean;
  live_emergency_stop?: boolean;
  can_place_live_order: boolean;
  effective_can_place_live_order?: boolean;
  unlock_pending_due_to_paper_readiness?: boolean;
  settings_saved_but_not_effective?: boolean;
  pending_blockers?: string[];
  pending_blocker_details?: Array<{ code: string; message: string }>;
  trading_badge: "test" | "live";
  warning_message: string;
}

export interface RuntimeSafetyValidationResponse {
  ok: boolean;
  blockers: string[];
  blocker_details?: Array<{ code: string; message: string }>;
  paper_readiness?: Record<string, unknown>;
  kill_switch?: KillSwitchStatusResponse;
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

export type LiveMarket = "domestic";

export interface LiveExecSession {
  session_id: string;
  user_id: string;
  status: "running" | "stopped";
  strategy_id: string;
  market: LiveMarket;
  execution_mode: "live_shadow" | "live_manual_approval";
  started_at_utc: string;
  stopped_at_utc?: string | null;
  last_tick_at_utc?: string | null;
  last_tick_summary?: Record<string, unknown>;
  last_error?: string | null;
  actor?: string;
  reason?: string;
}

export interface LiveExecStartRequest {
  strategy_id: string;
  market: LiveMarket;
  execution_mode: "live_shadow" | "live_manual_approval";
  actor?: string;
  reason?: string;
}

export interface LiveExecStopRequest {
  actor?: string;
  reason?: string;
}

export interface LiveExecStatusResponse {
  ok: boolean;
  config?: { trading_mode?: TradingMode; execution_mode_env?: ExecutionMode | string };
  safety?: RuntimeSafetyValidationResponse;
  session: LiveExecSession | null;
  session_running: boolean;
  supported_strategies: string[];
  counts?: { final_betting_candidates?: number; final_betting_pending_approvals?: number };
  blocked?: {
    start_blockers?: string[];
    submit_blockers?: string[];
    submit_blocker_details?: Array<{ code: string; message: string }>;
  };
  history?: LiveExecSession[];
}

export interface LiveExecTickResponse {
  ok: boolean;
  session: LiveExecSession;
  result: Record<string, unknown>;
  counts?: { final_betting_candidates?: number; final_betting_pending_approvals?: number };
}

export type LiveAutoMode = "aggressive" | "auto" | "passive";

export interface LiveAutoGuardedStartRequest {
  strategy_id: string;
  mode: LiveAutoMode;
  actor?: string;
  reason?: string;
}

export interface LiveAutoGuardedStopRequest {
  actor?: string;
  reason?: string;
}

export interface LiveAutoGuardedModeUpdateRequest {
  strategy_id: string;
  mode: LiveAutoMode;
  actor?: string;
  reason?: string;
}

export interface LiveAutoGuardedCandidateRow {
  status: string;
  strategy_id: string;
  symbol: string;
  side: "buy" | "sell" | "";
  quantity: number;
  price: number | null;
  score: number | null;
  reason: string;
  order_id: string | null;
  ts_utc: string | null;
}

export interface LiveAutoGuardedStatusResponse {
  ok: boolean;
  enabled: boolean;
  selected_strategy: string | null;
  effective_selected_strategy: string;
  supported_strategies: string[];
  mode_by_strategy: Record<string, LiveAutoMode>;
  mode_effective: LiveAutoMode;
  last_tick_at_utc: string | null;
  last_eval_at_utc: string | null;
  last_eval_strategies: string[];
  last_eval_candidates: LiveAutoGuardedCandidateRow[];
  submitted: { buys: Array<Record<string, unknown>>; sells: Array<Record<string, unknown>> };
  last_decision: string;
  last_reason: string;
  daily_buy_count: number;
  daily_sell_count: number;
}

export interface LiveAutoGuardedStartResponse {
  ok: boolean;
  enabled: boolean;
  selected_strategy: string | null;
  mode: LiveAutoMode;
}

export interface LiveAutoGuardedStopResponse {
  ok: boolean;
  enabled: boolean;
}

export interface LiveAutoGuardedTickResponse {
  ok: boolean;
  enabled: boolean;
  selected_strategy: string | null;
  effective_selected_strategy: string;
  mode_effective: LiveAutoMode;
  last_eval_strategies: string[];
  last_eval_candidates: LiveAutoGuardedCandidateRow[];
  submitted: { buys: Array<Record<string, unknown>>; sells: Array<Record<string, unknown>> };
  daily_buy_count: number;
  daily_sell_count: number;
  safety: RuntimeSafetyValidationResponse;
  meta_by_strategy?: Record<string, Record<string, unknown>>;
}

export interface LiveCompactPositionRow {
  symbol: string;
  quantity: number;
  average_price: number;
  current_price: number | null;
  market_value: number | null;
  pnl_pct: number | null;
}

export interface LiveCompactOpenOrderRow {
  order_id: string;
  symbol: string;
  side: string;
  remaining_quantity: number;
  price: number | null;
  created_at_utc: string;
}

export interface LiveCompactFillRow {
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  order_id: string;
  filled_at_utc: string;
}

export interface LiveTradingCompactDashboardResponse {
  live: {
    can_place_live_order: boolean;
    blockers: string[];
    bypass: boolean;
    emergency_stop: boolean;
    warning_message: string;
  };
  auto: {
    enabled: boolean;
    can_place_auto_order: boolean;
    selected_strategy: string;
    mode: LiveAutoMode;
    last_tick_at_utc: string | null;
    last_eval_at_utc: string | null;
    last_decision: string;
    last_reason: string;
    daily_buy_count: number;
    daily_sell_count: number;
    last_eval_candidates: LiveAutoGuardedCandidateRow[];
    submitted: { buys: Array<Record<string, unknown>>; sells: Array<Record<string, unknown>> };
  };
  strategies: Record<string, { shadow_candidates: unknown[]; auto_candidates: unknown[]; summary: Record<string, unknown> }>;
  account: {
    ok: boolean;
    error: string;
    positions: LiveCompactPositionRow[];
    open_orders: LiveCompactOpenOrderRow[];
    recent_fills: LiveCompactFillRow[];
  };
  raw?: Record<string, unknown>;
}
