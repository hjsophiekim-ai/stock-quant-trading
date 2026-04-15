import type { MarketStatusCard } from "./trading";

export type DashboardSystemStatus = "running" | "stopped" | "risk-off";

/** /api/dashboard/summary — 평탄 필드 + 중첩 운영 필드 병행 */
export interface MobileDashboardSummary {
  updated_at_utc?: string;
  mode: "paper" | "live";
  live_execution_armed?: boolean;
  account_status: "connected" | "disconnected" | "limited";
  today_return_pct: number;
  monthly_return_pct: number;
  cumulative_return_pct: number;
  position_count: number;
  realized_pnl: number;
  unrealized_pnl: number;
  system_status: DashboardSystemStatus;
  risk_banner: {
    level: "info" | "warning" | "critical";
    message: string;
  };
  broker?: { ok?: boolean; token_ok?: boolean; message?: string; kis_api_base?: string };
  runtime_engine?: Record<string, unknown>;
  portfolio?: { synced?: boolean; updated_at_utc?: string | null; warnings?: string[] };
  open_orders?: unknown[];
  recent_fills?: unknown[];
  market_regime?: Record<string, unknown>;
  strategy_signals?: Record<string, unknown>;
  last_heartbeat_utc?: string | null;
  recent_logs?: { source: string; message: string }[];
  alerts?: { portfolio_sync_risk_review?: boolean; runtime_risk_off?: boolean; broker_ok?: boolean };
  paper_trading_demo?: Record<string, unknown>;
  paper_trading?: {
    status?: string;
    strategy_id?: string | null;
    krx_session_state?: string | null;
    user_session_active?: boolean;
  };
  market_status_cards?: MarketStatusCard[];
  screener?: Record<string, unknown>;
}

export interface MobileRecentTrade {
  trade_id: string;
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  filled_at: string;
  status: "filled" | "cancelled" | "rejected";
}
