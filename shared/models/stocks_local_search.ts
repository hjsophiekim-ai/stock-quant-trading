/** 공통: 앱 내장 종목 한 줄 (KIS 공식 실시간 검색 아님) */
export interface LocalSymbolCatalogRow {
  symbol: string;
  name_kr: string;
}

/** ① GET /api/stocks/search-by-name */
export interface StockSearchByNameResponse {
  api_role: "name_search";
  title_ko: string;
  kis_official_search: boolean;
  description_ko: string;
  catalog_entry_count: number;
  query: string;
  match_count: number;
  matches: LocalSymbolCatalogRow[];
}

/** ② GET /api/stocks/search-by-symbol */
export interface StockSearchBySymbolResponse {
  api_role: "symbol_search";
  title_ko: string;
  kis_official_search: boolean;
  description_ko: string;
  catalog_entry_count: number;
  query: string;
  match_count: number;
  matches: LocalSymbolCatalogRow[];
}

/** ③ GET /api/stocks/strategy-candidates?strategy_id=swing_v1 */
export interface StrategyCandidatesResponse {
  api_role: "strategy_candidates";
  kind: string;
  strategy_id: string;
  title_ko: string;
  description_ko: string;
  screener: Record<string, unknown>;
  signal_engine: Record<string, unknown>;
}

/** 레거시: GET /api/stocks/local-symbol-search (이름·코드 혼합) */
export interface LocalSymbolSearchResponse {
  api_role: "legacy_combined_search";
  search_name: string;
  kis_official_search: boolean;
  description_ko: string;
  catalog_entry_count: number;
  query: string;
  match_count: number;
  matches: LocalSymbolCatalogRow[];
}
