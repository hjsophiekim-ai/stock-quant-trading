import React, { useEffect, useMemo, useState } from "react";
import { Button, SafeAreaView, ScrollView, Text, TextInput, View } from "react-native";

type Props = {
  backendUrl: string;
};

type StrategyOption = "swing_v1" | "bull_focus_v1" | "defensive_v1";

export default function PaperTradingScreen({ backendUrl }: Props) {
  const [strategyId, setStrategyId] = useState<StrategyOption>("swing_v1");
  const [status, setStatus] = useState("stopped");
  const [message, setMessage] = useState("");
  const [positions, setPositions] = useState<Array<{ symbol: string; quantity: number; average_price: number }>>([]);
  const [chartValues, setChartValues] = useState<number[]>([]);
  const [logs, setLogs] = useState<string[]>([]);

  const chartBars = useMemo(() => chartValues.map((v) => "▇".repeat(Math.max(1, Math.round(v * 10)))), [chartValues]);

  const refresh = async () => {
    try {
      const [statusRes, posRes, pnlRes, logsRes] = await Promise.all([
        fetch(`${backendUrl}/api/paper-trading/status`),
        fetch(`${backendUrl}/api/paper-trading/positions`),
        fetch(`${backendUrl}/api/paper-trading/pnl`),
        fetch(`${backendUrl}/api/paper-trading/logs`),
      ]);
      const statusData = await statusRes.json();
      const posData = await posRes.json();
      const pnlData = await pnlRes.json();
      const logsData = await logsRes.json();
      if (statusRes.ok) setStatus(statusData.status ?? "stopped");
      if (posRes.ok) setPositions(posData.items ?? []);
      if (pnlRes.ok) setChartValues((pnlData.chart ?? []).map((x: any) => Number(x.return_pct ?? 0)));
      if (logsRes.ok) setLogs((logsData.items ?? []).map((x: any) => String(x.message)));
    } catch {
      setMessage("network error");
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const start = async () => {
    try {
      const res = await fetch(`${backendUrl}/api/paper-trading/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy_id: strategyId }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data?.detail ?? "start failed");
        return;
      }
      setStatus(data.status ?? "running");
      setMessage("paper trading started");
      await refresh();
    } catch {
      setMessage("network error");
    }
  };

  const stop = async () => {
    try {
      const res = await fetch(`${backendUrl}/api/paper-trading/stop`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data?.detail ?? "stop failed");
        return;
      }
      setStatus(data.status ?? "stopped");
      setMessage("paper trading stopped");
      await refresh();
    } catch {
      setMessage("network error");
    }
  };

  return (
    <SafeAreaView>
      <ScrollView style={{ padding: 12 }}>
        <Text style={{ fontSize: 20, fontWeight: "bold", marginBottom: 8 }}>Paper Trading</Text>
        <Text>Mode: paper (live completely separated)</Text>
        <Text>Current Status: {status}</Text>
        <TextInput
          value={strategyId}
          onChangeText={(v) => setStrategyId((v as StrategyOption) || "swing_v1")}
          placeholder="strategy id"
          style={{ borderWidth: 1, borderColor: "#cbd5e1", padding: 8, marginVertical: 8 }}
        />
        <Button title="Start Paper Trading" onPress={start} />
        <View style={{ height: 8 }} />
        <Button title="Stop Paper Trading" onPress={stop} />
        <View style={{ height: 8 }} />
        <Button title="Refresh" onPress={refresh} />
        <Text style={{ marginTop: 8 }}>{message}</Text>

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>Current Positions</Text>
        {positions.map((p) => (
          <Text key={p.symbol}>
            {p.symbol} / qty={p.quantity} / avg={p.average_price}
          </Text>
        ))}

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>Return Chart (mock)</Text>
        {chartBars.map((bar, idx) => (
          <Text key={idx}>{bar}</Text>
        ))}

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>Recent Logs</Text>
        {logs.map((line, idx) => (
          <Text key={idx}>- {line}</Text>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}
