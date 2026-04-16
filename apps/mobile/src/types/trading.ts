/** Paper / dashboard에서 쓰는 시장 구분 */
export type MarketId = "domestic" | "us";

export type TradingMarket = MarketId;

/** 국내 Paper에서 선택 가능한 전략 (데스크톱 paper_strategy 와 동기) */
export type DomesticStrategyId =
  | "swing_v1"
  | "swing_relaxed_v1"
  | "swing_relaxed_v2"
  | "bull_focus_v1"
  | "defensive_v1"
  | "scalp_momentum_v1"
  | "scalp_momentum_v2"
  | "scalp_momentum_v3"
  | "final_betting_v1";

export const DOMESTIC_STRATEGY_OPTIONS: DomesticStrategyId[] = [
  "swing_v1",
  "swing_relaxed_v1",
  "swing_relaxed_v2",
  "bull_focus_v1",
  "defensive_v1",
  "scalp_momentum_v1",
  "scalp_momentum_v2",
  "scalp_momentum_v3",
  "final_betting_v1",
];

/** 미국 Paper용 (백엔드 구현 시 연결) */
export type USStrategyId = "us_swing_relaxed_v1" | "us_scalp_momentum_v1";

export const US_STRATEGY_OPTIONS: USStrategyId[] = ["us_swing_relaxed_v1", "us_scalp_momentum_v1"];

/**
 * US Paper 는 백엔드 `paper_strategy` + `/api/paper-trading/capabilities` 로 제공됩니다.
 * UI는 `capabilities.us_paper_supported` 가 false 일 때만 시작 버튼을 막습니다.
 */
export const US_PAPER_STRATEGIES_IMPLEMENTED = true;

export type SessionState = "premarket" | "regular" | "after_hours" | "closed" | string;

export interface PaperStatusResponse {
  mode?: string;
  market?: MarketId | string;
  status?: string;
  strategy_id?: string | null;
  session_state?: SessionState;
  user_session_active?: boolean;
  failure_streak?: number;
  last_error?: string | null;
  last_tick_at?: string | null;
  krx_session_state?: string;
}

export interface MarketStatusCard {
  market?: MarketId | string;
  title?: string;
  status?: string;
  session_state?: SessionState;
  message?: string;
}

export interface TradingPositionItem {
  symbol: string;
  quantity: number;
  average_price: number;
}

export interface TradingLogItem {
  ts?: string;
  level?: string;
  message?: string;
}

export interface SymbolSearchMatch {
  symbol?: string;
  name_kr?: string;
  name_en?: string;
  market?: string;
}

export interface SymbolSearchResponse {
  api_role?: string;
  market?: string;
  us_search_supported?: boolean;
  query?: string;
  match_count?: number;
  matches?: SymbolSearchMatch[];
  description_ko?: string;
}

export interface USSessionSummary {
  status?: string;
  strategy_id?: string | null;
  session_state?: SessionState;
  last_error?: string | null;
}
