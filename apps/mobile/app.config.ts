import type { ExpoConfig } from "expo/config";

const appEnv = process.env.APP_ENV ?? "development";
const isProd = appEnv === "production";

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
    adaptiveIcon: {
      foregroundImage: "./assets/adaptive-icon.png",
      backgroundColor: "#0f172a",
    },
  },
  extra: {
    appEnv,
    backendUrl: process.env.EXPO_PUBLIC_BACKEND_URL ?? "http://localhost:8000",
  },
};

export default config;
