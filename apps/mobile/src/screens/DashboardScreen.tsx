import React from "react";
import { Button, SafeAreaView, ScrollView, Text, View } from "react-native";

import { dashboardSummaryMock, recentTradesMock } from "../mock/dashboardMock";
import { clearAuth, getAuthState } from "../store/authStore";

type Props = {
  onOpenBrokerSettings: () => void;
};

export default function DashboardScreen({ onOpenBrokerSettings }: Props) {
  const state = getAuthState();
  const summary = dashboardSummaryMock;

  const cardStyle = {
    backgroundColor: "#f1f5f9",
    borderRadius: 8,
    padding: 10,
    marginBottom: 8,
  } as const;

  return (
    <SafeAreaView>
      <ScrollView style={{ padding: 12 }}>
        <Text style={{ fontSize: 20, fontWeight: "bold", marginBottom: 8 }}>Auto Trading Dashboard</Text>
        <Text style={{ marginBottom: 8 }}>User: {state.email ?? "-"}</Text>

        <View style={{ ...cardStyle, backgroundColor: "#fff7ed" }}>
          <Text>Risk Alert: {summary.risk_banner.message}</Text>
        </View>

        <View style={cardStyle}>
          <Text>현재 모드: {summary.mode}</Text>
          <Text>시스템 상태: {summary.system_status}</Text>
          <Text>계좌 상태: {summary.account_status}</Text>
        </View>
        <View style={cardStyle}>
          <Text>오늘 수익률: {summary.today_return_pct}%</Text>
          <Text>월간 수익률: {summary.monthly_return_pct}%</Text>
          <Text>누적 수익률: {summary.cumulative_return_pct}%</Text>
        </View>
        <View style={cardStyle}>
          <Text>보유 포지션 수: {summary.position_count}</Text>
          <Text>실현 손익: {summary.realized_pnl.toLocaleString()}</Text>
          <Text>미실현 손익: {summary.unrealized_pnl.toLocaleString()}</Text>
        </View>
        <View style={cardStyle}>
          <Text style={{ marginBottom: 4 }}>최근 거래 5건</Text>
          {recentTradesMock.map((trade) => (
            <Text key={trade.trade_id}>
              {trade.symbol} {trade.side.toUpperCase()} {trade.quantity} @ {trade.price}
            </Text>
          ))}
        </View>

        {/* TODO: Replace mock dashboard/trades with backend API
            - GET /api/dashboard/summary
            - GET /api/portfolio/summary
            - GET /api/trading/recent-trades
        */}

        <Button title="Broker Settings" onPress={onOpenBrokerSettings} />
        <View style={{ height: 8 }} />
        <Button title="Logout" onPress={clearAuth} />
      </ScrollView>
    </SafeAreaView>
  );
}
