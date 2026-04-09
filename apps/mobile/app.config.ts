import type { ExpoConfig } from "expo/config";

const appEnv = process.env.APP_ENV ?? "development";
const isProd = appEnv === "production";
const defaultDevBackendUrl = "http://127.0.0.1:8000";
const defaultProdBackendUrl = "https://stock-quant-backend.onrender.com";
const useHostedDefault = isProd || appEnv === "staging";
const defaultBackendUrl = useHostedDefault
  ? defaultProdBackendUrl
  : defaultDevBackendUrl;
const backendUrl = process.env.EXPO_PUBLIC_BACKEND_URL ?? defaultBackendUrl;

const config: ExpoConfig = {
  name: isProd ? "Stock Quant Trader" : "Stock Quant Trader (Dev)",
  slug: "stock-quant-trader",
  version: "0.1.0",
  orientation: "portrait",
  icon: "./assets/icon.png",
  userInterfaceStyle: "light",
  splash: {
    image: "./assets/splash.png",
    resizeMode: "contain",
    backgroundColor: "#0f172a",
  },
  ios: {
    supportsTablet: false,
    bundleIdentifier: isProd ? "com.stockquant.trader" : "com.stockquant.trader.dev",
  },
  android: {
    package: isProd ? "com.stockquant.trader" : "com.stockquant.trader.dev",
    versionCode: 1,
    adaptiveIcon: {
      foregroundImage: "./assets/adaptive-icon.png",
      backgroundColor: "#0f172a",
    },
    permissions: ["INTERNET"],
  },
  updates: {
    fallbackToCacheTimeout: 0,
  },
  extra: {
    appEnv,
    backendUrl,
  },
};

export default config;
