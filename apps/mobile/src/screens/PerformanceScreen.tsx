import React from "react";
import { SafeAreaView, ScrollView, Text, View } from "react-native";

const metrics = {
  daily: 0.52,
  weekly: 1.84,
  monthly: 4.21,
  cumulative: 13.37,
  realized: 2180000,
  unrealized: 340000,
  maxDrawdown: -6.9,
  winRate: 58.7,
  payoffRatio: 1.63,
};

const symbolRows = [
  { symbol: "005930", pnl: 390000 },
  { symbol: "000660", pnl: 210000 },
  { symbol: "035420", pnl: 120000 },
  { symbol: "051910", pnl: -50000 },
];

const strategyRows = [
  { strategy: "swing_v1", pnl: 840000 },
  { strategy: "bull_focus_v1", pnl: 520000 },
  { strategy: "defensive_v1", pnl: 160000 },
];

const regimeRows = [
  { regime: "bullish_trend", pnl: 960000 },
  { regime: "sideways", pnl: 180000 },
  { regime: "bearish_trend", pnl: 110000 },
  { regime: "high_volatility_risk", pnl: -12000 },
];

const chartMock = [0.1, 0.22, 0.18, 0.47, -0.11, 0.36, 0.52];

export default function PerformanceScreen() {
  const card = { backgroundColor: "#f8fafc", borderRadius: 8, padding: 10, marginBottom: 8 } as const;
  return (
    <SafeAreaView>
      <ScrollView style={{ padding: 12 }}>
        <Text style={{ fontSize: 20, fontWeight: "bold", marginBottom: 8 }}>Performance</Text>
        <View style={card}>
          <Text>일간 수익률: {metrics.daily}%</Text>
          <Text>주간 수익률: {metrics.weekly}%</Text>
          <Text>월간 수익률: {metrics.monthly}%</Text>
          <Text>누적 수익률: {metrics.cumulative}%</Text>
        </View>
        <View style={card}>
          <Text>실현 손익: {metrics.realized.toLocaleString()}</Text>
          <Text>미실현 손익: {metrics.unrealized.toLocaleString()}</Text>
          <Text>최대낙폭: {metrics.maxDrawdown}%</Text>
          <Text>승률: {metrics.winRate}%</Text>
          <Text>손익비: {metrics.payoffRatio}</Text>
        </View>
        <View style={card}>
          <Text style={{ fontWeight: "bold" }}>수익률 차트(mock)</Text>
          {chartMock.map((v, i) => (
            <Text key={i}>{`${v >= 0 ? "+" : ""}${v}% ` + "▇".repeat(Math.max(1, Math.round(Math.abs(v) * 10)))}</Text>
          ))}
        </View>
        <View style={card}>
          <Text style={{ fontWeight: "bold" }}>종목별 손익</Text>
          {symbolRows.map((x) => (
            <Text key={x.symbol}>
              {x.symbol}: {x.pnl.toLocaleString()}
            </Text>
          ))}
        </View>
        <View style={card}>
          <Text style={{ fontWeight: "bold" }}>전략별 손익</Text>
          {strategyRows.map((x) => (
            <Text key={x.strategy}>
              {x.strategy}: {x.pnl.toLocaleString()}
            </Text>
          ))}
        </View>
        <View style={card}>
          <Text style={{ fontWeight: "bold" }}>국면별 성과</Text>
          {regimeRows.map((x) => (
            <Text key={x.regime}>
              {x.regime}: {x.pnl.toLocaleString()}
            </Text>
          ))}
        </View>
        {/* TODO: Replace mock with API calls
            GET /api/performance/metrics
            GET /api/performance/pnl-history
            GET /api/performance/trade-history
            GET /api/performance/symbol-performance
            GET /api/performance/strategy-performance
            GET /api/performance/regime-performance
        */}
      </ScrollView>
    </SafeAreaView>
  );
}
