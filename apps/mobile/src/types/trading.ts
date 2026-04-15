export type TradingMarket = "domestic" | "us";

export type StrategyId =
  | "swing_v1"
  | "swing_relaxed_v1"
  | "swing_relaxed_v2"
  | "bull_focus_v1"
  | "defensive_v1"
  | "scalp_momentum_v1"
  | "scalp_momentum_v2"
  | "scalp_momentum_v3";

export const STRATEGY_OPTIONS: StrategyId[] = [
  "swing_v1",
  "swing_relaxed_v1",
  "swing_relaxed_v2",
  "bull_focus_v1",
  "defensive_v1",
  "scalp_momentum_v1",
  "scalp_momentum_v2",
  "scalp_momentum_v3",
];

export type SessionState = "premarket" | "regular" | "after_hours" | "closed" | string;

export interface MarketStatusCard {
  market?: TradingMarket | string;
  title?: string;
  status?: string;
  session_state?: SessionState;
  message?: string;
}
