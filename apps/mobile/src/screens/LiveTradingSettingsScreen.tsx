import React, { useState } from "react";
import { Button, SafeAreaView, ScrollView, Switch, Text, TextInput, View } from "react-native";

type Props = {
  backendUrl: string;
};

type SafetyStatus = {
  trading_mode: "paper" | "live";
  live_trading_flag: boolean;
  secondary_confirm_flag: boolean;
  extra_approval_flag: boolean;
  can_place_live_order: boolean;
  trading_badge: "test" | "live";
  warning_message: string;
};

export default function LiveTradingSettingsScreen({ backendUrl }: Props) {
  const [status, setStatus] = useState<SafetyStatus>({
    trading_mode: "paper",
    live_trading_flag: false,
    secondary_confirm_flag: false,
    extra_approval_flag: false,
    can_place_live_order: false,
    trading_badge: "test",
    warning_message: "LIVE 잠금 상태",
  });
  const [reason, setReason] = useState("운영자 수동 승인");
  const [killMessage, setKillMessage] = useState("");
  const [history, setHistory] = useState<Array<{ ts: string; actor: string; reason: string }>>([]);
  const [msg, setMsg] = useState("");

  const refresh = async () => {
    const statusRes = await fetch(`${backendUrl}/api/live-trading/status`);
    const statusData = await statusRes.json();
    if (statusRes.ok) setStatus(statusData);

    const killRes = await fetch(`${backendUrl}/api/live-trading/kill-switch-status`);
    const killData = await killRes.json();
    if (killRes.ok) {
      setKillMessage(
        killData.loss_limit_exceeded
          ? `손실 제한 초과 경고: daily=${killData.daily_loss_pct}% total=${killData.total_loss_pct}%`
          : "손실 제한 정상 범위",
      );
    }

    const histRes = await fetch(`${backendUrl}/api/live-trading/settings-history`);
    const histData = await histRes.json();
    if (histRes.ok) setHistory(histData.items ?? []);
  };

  const save = async () => {
    const res = await fetch(`${backendUrl}/api/live-trading/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        live_trading_flag: status.live_trading_flag,
        secondary_confirm_flag: status.secondary_confirm_flag,
        extra_approval_flag: status.extra_approval_flag,
        reason,
        actor: "mobile-user",
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMsg(data?.detail ?? "저장 실패");
      return;
    }
    setStatus(data);
    setMsg(data.warning_message ?? "저장 완료");
    await refresh();
  };

  return (
    <SafeAreaView>
      <ScrollView style={{ padding: 12 }}>
        <Text style={{ fontSize: 20, fontWeight: "bold" }}>Live Trading Settings</Text>
        <Text style={{ color: "#b91c1c", marginTop: 6 }}>
          경고: 실거래는 고위험입니다. 명시적 다중 승인 없이는 잠금 해제되지 않습니다.
        </Text>
        <Text style={{ marginTop: 8 }}>Badge: {status.trading_badge.toUpperCase()}</Text>
        <Text>Mode: {status.trading_mode}</Text>
        <Text>Can Place Live Order: {status.can_place_live_order ? "YES" : "NO"}</Text>
        <Text style={{ marginBottom: 8 }}>{status.warning_message}</Text>

        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <Text>1) Live Enable Flag</Text>
          <Switch value={status.live_trading_flag} onValueChange={(v) => setStatus({ ...status, live_trading_flag: v })} />
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <Text>2) Secondary Confirmation</Text>
          <Switch
            value={status.secondary_confirm_flag}
            onValueChange={(v) => setStatus({ ...status, secondary_confirm_flag: v })}
          />
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <Text>3) Extra Approval</Text>
          <Switch value={status.extra_approval_flag} onValueChange={(v) => setStatus({ ...status, extra_approval_flag: v })} />
        </View>
        <TextInput value={reason} onChangeText={setReason} placeholder="변경 사유" style={{ borderWidth: 1, padding: 8, marginTop: 8 }} />
        <Button title="Save Safety Settings" onPress={save} />
        <View style={{ height: 8 }} />
        <Button title="Refresh Status" onPress={refresh} />
        <Text style={{ marginTop: 8 }}>{msg}</Text>
        <Text style={{ marginTop: 8, color: "#b91c1c" }}>{killMessage}</Text>

        <Text style={{ marginTop: 12, fontWeight: "bold" }}>Settings Change History</Text>
        {history.slice(0, 10).map((h, idx) => (
          <Text key={`${h.ts}-${idx}`}>
            {h.ts} / {h.actor} / {h.reason}
          </Text>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}
