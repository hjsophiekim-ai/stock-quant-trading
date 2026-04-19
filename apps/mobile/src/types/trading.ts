/** Paper / dashboard에서 쓰는 시장 구분 */
export type MarketId = "domestic" | "us";

export type TradingMarket = MarketId;

/** 기본 UI에 노출하는 국내 Paper 전략(메인 3 + 실험 2) — 백엔드 `paper_strategy` 와 동기 */
export const DOMESTIC_STRATEGY_OPTIONS = [
  "swing_relaxed_v2",
  "final_betting_v1",
  "scalp_macd_rsi_3m_v1",
  "scalp_momentum_v2",
  "scalp_momentum_v3",
] as const;

/** 과거 로그/세션 호환용 (registry 유지, UI 기본 목록에서는 제외) */
export const DOMESTIC_STRATEGY_LEGACY_OPTIONS = [
  "swing_v1",
  "swing_relaxed_v1",
  "bull_focus_v1",
  "defensive_v1",
  "scalp_momentum_v1",
] as const;

export type DomesticStrategyIdMain = (typeof DOMESTIC_STRATEGY_OPTIONS)[number];
export type DomesticStrategyIdLegacy = (typeof DOMESTIC_STRATEGY_LEGACY_OPTIONS)[number];
export type DomesticStrategyId = DomesticStrategyIdMain | DomesticStrategyIdLegacy;

/** 미국 Paper용 (백엔드 `paper_strategy` + capabilities) */
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
  /** 세션의 paper 시장 (domestic | us) */
  paper_market?: string | null;
  /** GET status 쿼리로 요청한 market */
  requested_market?: string | null;
  market_mismatch?: boolean;
  session_state?: SessionState;
  user_session_active?: boolean;
  failure_streak?: number;
  last_error?: string | null;
  last_tick_at?: string | null;
  krx_session_state?: string;
  backend_git_sha?: string;
  backend_build_time?: string;
  backend_app_version?: string;
  final_betting_enabled_effective?: boolean;
  paper_start_diagnostics?: Record<string, unknown>;
  manual_override_enabled?: boolean;
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
