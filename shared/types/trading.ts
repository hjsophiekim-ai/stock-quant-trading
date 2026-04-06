export type TradingMode = "paper" | "live";

export interface RuntimeSafetyState {
  tradingMode: TradingMode;
  liveTrading: boolean;
  liveTradingConfirm: boolean;
  canPlaceLiveOrder: boolean;
}
