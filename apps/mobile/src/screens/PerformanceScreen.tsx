import React, { useEffect, useMemo, useState } from "react";
import { SafeAreaView, ScrollView, Text, View } from "react-native";

import { authFetch } from "../lib/authFetch";

type Props = { backendUrl: string };

export default function PerformanceScreen({ backendUrl }: Props) {
  const [metrics, setMetrics] = useState<any>(null);
  const [symbolRows, setSymbolRows] = useState<any[]>([]);
  const [strategyRows, setStrategyRows] = useState<any[]>([]);
  const [regimeRows, setRegimeRows] = useState<any[]>([]);
  const [chartValues, setChartValues] = useState<number[]>([]);
  const [message, setMessage] = useState("");
  const chartMock = useMemo(() => chartValues, [chartValues]);

  useEffect(() => {
    const load = async () => {
      try {
        const [metricsRes, pnlRes, symbolRes, strategyRes, regimeRes] = await Promise.all([
          authFetch(backendUrl, `/api/performance/metrics`),
          authFetch(backendUrl, `/api/performance/pnl-history`),
          authFetch(backendUrl, `/api/performance/symbol-performance`),
          authFetch(backendUrl, `/api/performance/strategy-performance`),
          authFetch(backendUrl, `/api/performance/regime-performance`),
        ]);
        const m = await metricsRes.json();
        const p = await pnlRes.json();
        const sy = await symbolRes.json();
        const st = await strategyRes.json();
        const rg = await regimeRes.json();
        if (!metricsRes.ok) {
          setMessage(m?.detail ?? "performance load failed");
          return;
        }
        setMetrics(m);
        setChartValues((p.items ?? []).map((x: any) => Number(x.daily_return_pct ?? 0)));
        setSymbolRows(sy.items ?? []);
        setStrategyRows(st.items ?? []);
        setRegimeRows(rg.items ?? []);
      } catch (e) {
        if (e instanceof Error && e.message === "SESSION_EXPIRED") {
          setMessage("세션이 만료되었습니다. 다시 로그인해 주세요.");
          return;
        }
        setMessage("network error");
      }
    };
    load();
  }, [backendUrl]);
  const card = { backgroundColor: "#f8fafc", borderRadius: 8, padding: 10, marginBottom: 8 } as const;
  return (
    <SafeAreaView>
      <ScrollView style={{ padding: 12 }}>
        <Text style={{ fontSize: 20, fontWeight: "bold", marginBottom: 8 }}>Performance</Text>
        <Text>{message}</Text>
        {metrics ? (
          <>
            <View style={card}>
              <Text>일간 수익률: {metrics.daily_return_pct}%</Text>
              <Text>주간 수익률: {metrics.weekly_return_pct}%</Text>
              <Text>월간 수익률: {metrics.monthly_return_pct}%</Text>
              <Text>누적 수익률: {metrics.cumulative_return_pct}%</Text>
            </View>
            <View style={card}>
              <Text>실현 손익: {Number(metrics.realized_pnl).toLocaleString()}</Text>
              <Text>미실현 손익: {Number(metrics.unrealized_pnl).toLocaleString()}</Text>
              <Text>최대낙폭: {metrics.max_drawdown_pct}%</Text>
              <Text>승률: {metrics.win_rate_pct}%</Text>
              <Text>손익비: {metrics.payoff_ratio}</Text>
            </View>
          </>
        ) : (
          <Text>Loading performance...</Text>
        )}
        <View style={card}>
          <Text style={{ fontWeight: "bold" }}>수익률 차트(실데이터 기반)</Text>
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
            <Text key={x.strategy_id}>
              {x.strategy_id}: {Number(x.pnl).toLocaleString()}
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
      </ScrollView>
    </SafeAreaView>
  );
}
