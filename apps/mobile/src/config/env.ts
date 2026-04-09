import Constants from "expo-constants";

type ExpoExtra = {
  backendUrl?: string;
  appEnv?: string;
};

const extra = (Constants.expoConfig?.extra ?? {}) as ExpoExtra;

const appEnv = extra.appEnv ?? "development";
const fallbackBackendUrl =
  appEnv === "production" || appEnv === "staging"
    ? "https://stock-quant-backend.onrender.com"
    : "http://127.0.0.1:8000";

/** 빌드 시 app.config.ts -> extra.backendUrl 로 주입. 일반 사용자는 URL 수동 입력이 필요 없습니다. */
export const BACKEND_URL: string = extra.backendUrl ?? fallbackBackendUrl;
export const APP_ENV: string = appEnv;
