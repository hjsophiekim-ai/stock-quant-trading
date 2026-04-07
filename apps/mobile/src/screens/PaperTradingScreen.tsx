import React, { useMemo, useState } from "react";
import { Button, SafeAreaView, ScrollView, Text, TextInput, View } from "react-native";

type Props = {
  backendUrl: string;
};

type StrategyOption = "swing_v1" | "bull_focus_v1" | "defensive_v1";

const mockPositions = [
  { symbol: "005930", quantity: 2, average_price: 77000 },
  { symbol: "000660", quantity: 1, average_price: 168000 },
];
const mockChart = [0.1, 0.12, 0.18, 0.15, 0.23, 0.31, 0.29];
const mockLogs = [
  "Paper trading started with strategy=swing_v1",
  "Risk engine approved buy signal for 005930",
  "Filled BUY 2 @ 77000",
];

export default function PaperTradingScreen({ backendUrl }: Props) {
  const [strategyId, setStrategyId] = useState<StrategyOption>("swing_v1");
  const [status, setStatus] = useState("stopped");
  const [message, setMessage] = useState("");

  const chartBars = useMemo(() => mockChart.map((v) => "▇".repeat(Math.max(1, Math.round(v * 10)))), []);

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
        <Text style={{ marginTop: 8 }}>{message}</Text>

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>Current Positions</Text>
        {mockPositions.map((p) => (
          <Text key={p.symbol}>
            {p.symbol} / qty={p.quantity} / avg={p.average_price}
          </Text>
        ))}

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>Return Chart (mock)</Text>
        {chartBars.map((bar, idx) => (
          <Text key={idx}>{bar}</Text>
        ))}

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>Recent Logs</Text>
        {mockLogs.map((line, idx) => (
          <Text key={idx}>- {line}</Text>
        ))}

        {/* TODO: replace mock sections with real API
            GET /api/paper-trading/status
            GET /api/paper-trading/positions
            GET /api/paper-trading/pnl
            GET /api/paper-trading/logs
        */}
      </ScrollView>
    </SafeAreaView>
  );
}
