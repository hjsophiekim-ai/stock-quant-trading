import React, { useEffect, useState } from "react";

import BrokerSettingsScreen from "./screens/BrokerSettingsScreen";
import DashboardScreen from "./screens/DashboardScreen";
import LoginScreen from "./screens/LoginScreen";
import { AuthState, getAuthState, subscribeAuth } from "./store/authStore";

const BACKEND_URL = "http://localhost:8000";

export default function App() {
  const [auth, setAuth] = useState<AuthState>(getAuthState());
  const [screen, setScreen] = useState<"dashboard" | "broker-settings">("dashboard");

  useEffect(() => {
    return subscribeAuth(setAuth);
  }, []);

  if (!auth.accessToken) {
    return <LoginScreen backendUrl={BACKEND_URL} />;
  }
  if (screen === "broker-settings") {
    return <BrokerSettingsScreen backendUrl={BACKEND_URL} onBack={() => setScreen("dashboard")} />;
  }
  return <DashboardScreen onOpenBrokerSettings={() => setScreen("broker-settings")} />;
}
