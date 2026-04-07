import Constants from "expo-constants";

type ExpoExtra = {
  backendUrl?: string;
  appEnv?: string;
};

const extra = (Constants.expoConfig?.extra ?? {}) as ExpoExtra;

export const BACKEND_URL: string = extra.backendUrl ?? "http://localhost:8000";
export const APP_ENV: string = extra.appEnv ?? "development";
