export type SystemStatus = "running" | "stopped" | "risk-off";

export interface RiskBanner {
  level: "info" | "warning" | "critical";
  message: string;
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
