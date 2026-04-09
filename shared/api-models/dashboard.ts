export type SystemStatus = "running" | "stopped" | "risk-off";

export interface RiskBanner {
  level: "info" | "warning" | "critical";
  message: string;
}

export interface DashboardPerformanceAligned {
  today_return_pct: number;
  monthly_return_pct: number;
  cumulative_return_pct: number;
  net_cumulative_return_pct: number;
  gross_realized_pnl: number;
  total_fees: number;
  total_taxes: number;
  net_realized_pnl: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  payoff_ratio: number;
  data_quality?: Record<string, unknown>;
  fee_rates_applied?: Record<string, number>;
  assumptions_tail?: Array<{ id: string; text: string }>;
}

export interface DashboardSummaryResponse {
  mode: "paper" | "live";
  account_status: "connected" | "disconnected" | "limited";
  today_return_pct: number;
  monthly_return_pct: number;
  cumulative_return_pct: number;
  position_count: number;
  realized_pnl: number;
  unrealized_pnl: number;
  system_status: SystemStatus;
  risk_banner: RiskBanner;
  performance_aligned?: DashboardPerformanceAligned;
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
