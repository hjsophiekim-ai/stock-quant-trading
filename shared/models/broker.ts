export type TradingMode = "paper" | "live";
export type BrokerConnectionStatus = "unknown" | "success" | "failed";

export interface BrokerAccountUpsertRequest {
  kis_app_key: string;
  kis_app_secret: string;
  kis_account_no: string;
  kis_account_product_code: string;
  trading_mode: TradingMode;
}

export interface BrokerAccountResponse {
  id: string;
  user_id: string;
  kis_app_key_masked: string;
  kis_account_no_masked: string;
  kis_account_product_code: string;
  trading_mode: TradingMode;
  connection_status: BrokerConnectionStatus;
  connection_message?: string | null;
  last_tested_at?: string | null;
  updated_at: string;
  created_at: string;
}

export interface BrokerConnectionTestResponse {
  ok: boolean;
  status: BrokerConnectionStatus;
  message: string;
}
