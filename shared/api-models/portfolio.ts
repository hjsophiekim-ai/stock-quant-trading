export interface PortfolioSummaryResponse {
  equity: number;
  daily_pnl: number;
  cumulative_return_pct: number;
  positions: Array<{
    symbol: string;
    quantity: number;
    average_price: number;
  }>;
}
