import React, { useEffect, useState } from "react";
import { ActivityIndicator, Button, SafeAreaView, View } from "react-native";

import BrokerSettingsScreen from "./screens/BrokerSettingsScreen";
import { APP_ENV, BACKEND_URL } from "./config/env";
import DashboardScreen from "./screens/DashboardScreen";
import LiveTradingSettingsScreen from "./screens/LiveTradingSettingsScreen";
import LoginScreen from "./screens/LoginScreen";
import OnboardingScreen from "./screens/OnboardingScreen";
import PaperTradingScreen from "./screens/PaperTradingScreen";
import PerformanceScreen from "./screens/PerformanceScreen";
import {
  clearPersistedAuth,
  getOnboardingDone,
  loadPersistedAuth,
  refreshTokens,
  savePersistedAuth,
  validateAccessToken,
} from "./lib/session";
import { AuthState, getAuthState, setAuth, subscribeAuth } from "./store/authStore";

export default function App() {
  const [auth, setAuthView] = useState<AuthState>(getAuthState());
  const [tab, setTab] = useState<
    "dashboard" | "broker-settings" | "paper-trading" | "live-settings" | "performance"
  >("dashboard");
  const [bootPhase, setBootPhase] = useState<"loading" | "onboarding" | "ready">("loading");
  const [showOnboarding, setShowOnboarding] = useState(false);

  useEffect(() => {
    return subscribeAuth(setAuthView);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const isProduction = APP_ENV === "production";
      const onboarded = await getOnboardingDone();
      if (cancelled) return;
      if (!isProduction && !onboarded) {
        setShowOnboarding(true);
        setBootPhase("onboarding");
        return;
      }
      const stored = await loadPersistedAuth();
      if (stored && stored.accessToken) {
        let access = stored.accessToken;
        let refresh = stored.refreshToken;
        let email = stored.email;
        const valid = await validateAccessToken(BACKEND_URL, access);
        if (!valid && refresh) {
          const pair = await refreshTokens(BACKEND_URL, refresh);
          if (pair) {
            access = pair.access_token;
            refresh = pair.refresh_token;
            await savePersistedAuth({
              accessToken: access,
              refreshToken: refresh,
              email,
              remember: true,
            });
          }
        }
        if (cancelled) return;
        const stillValid = await validateAccessToken(BACKEND_URL, access);
        if (stillValid) {
          setAuth({ accessToken: access, refreshToken: refresh, email });
        } else {
          await clearPersistedAuth();
          setAuth({ accessToken: null, refreshToken: null, email: null });
        }
      }
      if (!cancelled) setBootPhase("ready");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (bootPhase === "loading") {
    return (
      <SafeAreaView style={{ flex: 1, justifyContent: "center", alignItems: "center" }}>
        <ActivityIndicator size="large" />
      </SafeAreaView>
    );
  }

  if (bootPhase === "onboarding" && showOnboarding) {
    return (
      <OnboardingScreen
        onComplete={() => {
          setShowOnboarding(false);
          setBootPhase("ready");
        }}
      />
    );
  }

  if (!auth.accessToken) {
    return <LoginScreen backendUrl={BACKEND_URL} />;
  }

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <View style={{ flex: 1 }}>
        {tab === "dashboard" ? (
          <DashboardScreen backendUrl={BACKEND_URL} onOpenBrokerSettings={() => setTab("broker-settings")} />
        ) : tab === "paper-trading" ? (
          <PaperTradingScreen
            backendUrl={BACKEND_URL}
            onOpenDashboard={() => setTab("dashboard")}
            onOpenPerformance={() => setTab("performance")}
          />
        ) : tab === "live-settings" ? (
          <LiveTradingSettingsScreen backendUrl={BACKEND_URL} />
        ) : tab === "performance" ? (
          <PerformanceScreen backendUrl={BACKEND_URL} />
        ) : (
          <BrokerSettingsScreen backendUrl={BACKEND_URL} onBack={() => setTab("dashboard")} />
        )}
      </View>
      <View style={{ flexDirection: "row", justifyContent: "space-around", padding: 8 }}>
        <Button title="대시보드" onPress={() => setTab("dashboard")} />
        <Button title="Paper" onPress={() => setTab("paper-trading")} />
        <Button title="성과" onPress={() => setTab("performance")} />
        <Button title="Live" onPress={() => setTab("live-settings")} />
        <Button title="브로커" onPress={() => setTab("broker-settings")} />
      </View>
    </SafeAreaView>
  );
}
