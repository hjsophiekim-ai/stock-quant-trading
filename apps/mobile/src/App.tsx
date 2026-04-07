import React, { useEffect, useState } from "react";
import { Button, SafeAreaView, View } from "react-native";

import BrokerSettingsScreen from "./screens/BrokerSettingsScreen";
import { BACKEND_URL } from "./config/env";
import DashboardScreen from "./screens/DashboardScreen";
import LiveTradingSettingsScreen from "./screens/LiveTradingSettingsScreen";
import LoginScreen from "./screens/LoginScreen";
import PaperTradingScreen from "./screens/PaperTradingScreen";
import PerformanceScreen from "./screens/PerformanceScreen";
import { AuthState, getAuthState, subscribeAuth } from "./store/authStore";

export default function App() {
  const [auth, setAuth] = useState<AuthState>(getAuthState());
  const [tab, setTab] = useState<
    "dashboard" | "broker-settings" | "paper-trading" | "live-settings" | "performance"
  >("dashboard");

  useEffect(() => {
    return subscribeAuth(setAuth);
  }, []);

  if (!auth.accessToken) {
    return <LoginScreen backendUrl={BACKEND_URL} />;
  }

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <View style={{ flex: 1 }}>
        {tab === "dashboard" ? (
          <DashboardScreen backendUrl={BACKEND_URL} onOpenBrokerSettings={() => setTab("broker-settings")} />
        ) : tab === "paper-trading" ? (
          <PaperTradingScreen backendUrl={BACKEND_URL} />
        ) : tab === "live-settings" ? (
          <LiveTradingSettingsScreen backendUrl={BACKEND_URL} />
        ) : tab === "performance" ? (
          <PerformanceScreen backendUrl={BACKEND_URL} />
        ) : (
          <BrokerSettingsScreen backendUrl={BACKEND_URL} onBack={() => setTab("dashboard")} />
        )}
      </View>
      <View style={{ flexDirection: "row", justifyContent: "space-around", padding: 8 }}>
        <Button title="Dashboard" onPress={() => setTab("dashboard")} />
        <Button title="Paper" onPress={() => setTab("paper-trading")} />
        <Button title="Perf" onPress={() => setTab("performance")} />
        <Button title="Live" onPress={() => setTab("live-settings")} />
        <Button title="Broker" onPress={() => setTab("broker-settings")} />
      </View>
    </SafeAreaView>
  );
}
