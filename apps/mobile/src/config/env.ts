import Constants from "expo-constants";

type ExpoExtra = {
  backendUrl?: string;
  appEnv?: string;
};

const extra = (Constants.expoConfig?.extra ?? {}) as ExpoExtra;

/** 빌드 시 app.config.ts -> extra.backendUrl 로 주입. 일반 사용자는 URL 수동 입력이 필요 없습니다. */
export const BACKEND_URL: string = extra.backendUrl ?? "https://api.stock-quant.example.com";
export const APP_ENV: string = extra.appEnv ?? "development";
