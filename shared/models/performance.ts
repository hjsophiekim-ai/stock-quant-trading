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
  /** 자산(equity) 기준 누적%; cumulative_return_pct 와 동일 별칭 */
  net_cumulative_return_pct?: number;
  realized_pnl: number;
  unrealized_pnl: number;
  /** 매도가 기준 매매차읡(매수 순가 기준), 세전 */
  gross_realized_pnl?: number;
  total_fees?: number;
  total_taxes?: number;
  /** FIFO 순실현(매도 순현금 − 매입총비용) */
  net_realized_pnl?: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  payoff_ratio: number;
  realized_pnl_fifo_total?: number;
  realized_pnl_avg_cost_total?: number;
  data_source?: string;
  value_sources?: Record<string, string>;
  calculation_basis?: Record<string, unknown>;
  assumptions?: Array<{ id: string; text: string }>;
  data_quality?: Record<string, unknown>;
  display_labels_ko?: Record<string, { label: string; hint: string }>;
  fee_rates_applied?: { kis_buy_fee_rate: number; kis_sell_fee_rate: number; krx_sell_tax_rate: number };
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
  gross_pnl?: number;
  net_pnl?: number;
  fee?: number;
  buy_fee?: number;
  sell_fee?: number;
  tax?: number;
  gross_sell_krw?: number;
  realized_pnl_fifo?: number;
  realized_pnl_avg_cost?: number;
  result: "win" | "loss" | "flat";
  quantity?: number;
  price?: number;
  filled_at?: string;
  fee_input_mode?: string;
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
