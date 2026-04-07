export type UserRole = "admin" | "user";

export interface RegisterRequest {
  email: string;
  password: string;
  display_name: string;
  role?: UserRole;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RefreshTokenRequest {
  refresh_token: string;
}

export interface LogoutRequest {
  refresh_token: string;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: UserRole;
  settings: Record<string, string>;
  broker_accounts: string[];
  created_at: string;
}

export interface TokenPairResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  access_expires_in_sec: number;
  refresh_expires_in_sec: number;
}
