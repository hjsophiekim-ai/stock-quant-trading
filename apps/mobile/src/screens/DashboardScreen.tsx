import React from "react";
import { Button, SafeAreaView, Text } from "react-native";

import { clearAuth, getAuthState } from "../store/authStore";

type Props = {
  onOpenBrokerSettings: () => void;
};

export default function DashboardScreen({ onOpenBrokerSettings }: Props) {
  const state = getAuthState();
  return (
    <SafeAreaView>
      <Text>Mobile Dashboard</Text>
      <Text>User: {state.email ?? "-"}</Text>
      <Button title="Broker Settings" onPress={onOpenBrokerSettings} />
      <Button title="Logout" onPress={clearAuth} />
    </SafeAreaView>
  );
}
