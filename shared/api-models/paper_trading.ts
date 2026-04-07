export type PaperTradingSystemStatus = "running" | "stopped" | "risk-off";

export interface PaperTradingStartRequest {
  strategy_id: string;
}

export interface PaperTradingStatusResponse {
  mode: "paper";
  status: PaperTradingSystemStatus;
  strategy_id: string | null;
  started_at: string | null;
  last_heartbeat_at: string | null;
}

export interface PaperPositionItem {
  symbol: string;
  quantity: number;
  average_price: number;
}

export interface PaperPnlPoint {
  ts: string;
  return_pct: number;
}

export interface PaperPnlResponse {
  today_return_pct: number;
  monthly_return_pct: number;
  cumulative_return_pct: number;
  realized_pnl: number;
  unrealized_pnl: number;
  chart: PaperPnlPoint[];
}

export interface PaperLogItem {
  ts: string;
  level: "info" | "warning" | "error";
  message: string;
}
