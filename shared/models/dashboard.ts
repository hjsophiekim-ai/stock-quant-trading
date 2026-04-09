export type DashboardMode = "paper" | "live";
export type DashboardSystemStatus = "running" | "stopped" | "risk-off";

export interface RiskBanner {
  level: "info" | "warning" | "critical";
  message: string;
}

/** /api/performance/metrics 와 동일 정의의 요약(필터 없음) */
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
  performance_aligned?: DashboardPerformanceAligned;
}
