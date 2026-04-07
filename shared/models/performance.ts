export interface PerformanceFilterQuery {
  start_date?: string;
  end_date?: string;
  strategy_id?: string;
  symbol?: string;
}

export interface PerformanceMetrics {
  daily_return_pct: number;
  weekly_return_pct: number;
  monthly_return_pct: number;
  cumulative_return_pct: number;
  realized_pnl: number;
  unrealized_pnl: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  payoff_ratio: number;
}

export interface PnlHistoryPoint {
  date: string;
  daily_return_pct: number;
  equity: number;
}

export interface TradeHistoryItem {
  trade_id: string;
  symbol: string;
  strategy_id: string;
  pnl: number;
  result: "win" | "loss";
}

export interface SymbolPerformanceItem {
  symbol: string;
  pnl: number;
  return_pct: number;
  win_rate_pct: number;
}

export interface StrategyPerformanceItem {
  strategy_id: string;
  pnl: number;
  return_pct: number;
  win_rate_pct: number;
}

export interface RegimePerformanceItem {
  regime: "bullish_trend" | "bearish_trend" | "sideways" | "high_volatility_risk";
  pnl: number;
  return_pct: number;
  win_rate_pct: number;
}

export interface PerformanceMetricsResponse extends PerformanceMetrics {}

export interface PnlHistoryResponse {
  items: PnlHistoryPoint[];
}

export interface TradeHistoryResponse {
  items: TradeHistoryItem[];
}

export interface SymbolPerformanceResponse {
  items: SymbolPerformanceItem[];
}

export interface StrategyPerformanceResponse {
  items: StrategyPerformanceItem[];
}

export interface RegimePerformanceResponse {
  items: RegimePerformanceItem[];
}
