export type DashboardMode = "paper" | "live";
export type DashboardSystemStatus = "running" | "stopped" | "risk-off";

export interface RiskBanner {
  level: "info" | "warning" | "critical";
  message: string;
}

export interface DashboardSummaryResponse {
  mode: DashboardMode;
  account_status: "connected" | "disconnected" | "limited";
  today_return_pct: number;
  monthly_return_pct: number;
  cumulative_return_pct: number;
  position_count: number;
  realized_pnl: number;
  unrealized_pnl: number;
  system_status: DashboardSystemStatus;
  risk_banner: RiskBanner;
}
