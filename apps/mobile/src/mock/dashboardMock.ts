import { MobileDashboardSummary, MobileRecentTrade } from "../types/dashboard";

export const dashboardSummaryMock: MobileDashboardSummary = {
  mode: "paper",
  account_status: "connected",
  today_return_pct: 0.41,
  monthly_return_pct: 4.2,
  cumulative_return_pct: 12.8,
  position_count: 4,
  realized_pnl: 1840000,
  unrealized_pnl: 260000,
  system_status: "running",
  risk_banner: {
    level: "warning",
    message: "연속 손실 2회 감지: 신규 진입 크기 자동 축소 중",
  },
};

export const recentTradesMock: MobileRecentTrade[] = [
  {
    trade_id: "T-20260406-0005",
    symbol: "005930",
    side: "sell",
    quantity: 5,
    price: 78400,
    filled_at: "2026-04-06T13:28:00+09:00",
    status: "filled",
  },
  {
    trade_id: "T-20260406-0004",
    symbol: "000660",
    side: "buy",
    quantity: 2,
    price: 170500,
    filled_at: "2026-04-06T11:17:00+09:00",
    status: "filled",
  },
  {
    trade_id: "T-20260405-0011",
    symbol: "035420",
    side: "sell",
    quantity: 4,
    price: 188500,
    filled_at: "2026-04-05T14:42:00+09:00",
    status: "filled",
  },
  {
    trade_id: "T-20260405-0009",
    symbol: "207940",
    side: "buy",
    quantity: 1,
    price: 790000,
    filled_at: "2026-04-05T10:03:00+09:00",
    status: "filled",
  },
  {
    trade_id: "T-20260404-0002",
    symbol: "051910",
    side: "buy",
    quantity: 3,
    price: 394000,
    filled_at: "2026-04-04T09:22:00+09:00",
    status: "filled",
  },
];
