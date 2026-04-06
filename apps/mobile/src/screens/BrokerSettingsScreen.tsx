import React, { useMemo, useState } from "react";
import { Button, SafeAreaView, Text, TextInput } from "react-native";

import { getAuthState } from "../store/authStore";

type Props = {
  backendUrl: string;
  onBack: () => void;
};

type FormState = {
  kis_app_key: string;
  kis_app_secret: string;
  kis_account_no: string;
  kis_account_product_code: string;
  trading_mode: "paper" | "live";
};

const initialForm: FormState = {
  kis_app_key: "",
  kis_app_secret: "",
  kis_account_no: "",
  kis_account_product_code: "",
  trading_mode: "paper",
};

export default function BrokerSettingsScreen({ backendUrl, onBack }: Props) {
  const [form, setForm] = useState<FormState>(initialForm);
  const [statusText, setStatusText] = useState("unknown");
  const [message, setMessage] = useState("");

  const auth = getAuthState();
  const isValid = useMemo(() => {
    return (
      form.kis_app_key.trim().length >= 8 &&
      form.kis_app_secret.trim().length >= 8 &&
      form.kis_account_no.trim().length >= 4 &&
      form.kis_account_product_code.trim().length >= 1
    );
  }, [form]);

  const authHeader = auth.accessToken ? { Authorization: `Bearer ${auth.accessToken}` } : {};

  const save = async () => {
    if (!isValid) {
      setMessage("입력값을 확인해주세요.");
      return;
    }
    try {
      const res = await fetch(`${backendUrl}/api/broker-accounts/me`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data?.detail ?? "저장 실패");
        return;
      }
      setStatusText(data.connection_status ?? "unknown");
      setMessage("저장 완료");
    } catch {
      setMessage("네트워크 오류");
    }
  };

  const testConnection = async () => {
    try {
      const res = await fetch(`${backendUrl}/api/broker-accounts/me/test-connection`, {
        method: "POST",
        headers: authHeader,
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data?.detail ?? "연결 테스트 실패");
        return;
      }
      setStatusText(data.status);
      setMessage(data.message);
    } catch {
      setMessage("네트워크 오류");
    }
  };

  return (
    <SafeAreaView>
      <Text>Broker Settings</Text>
      <Text>Status: {statusText}</Text>
      <TextInput placeholder="KIS_APP_KEY" value={form.kis_app_key} onChangeText={(v) => setForm({ ...form, kis_app_key: v })} />
      <TextInput
        placeholder="KIS_APP_SECRET"
        value={form.kis_app_secret}
        onChangeText={(v) => setForm({ ...form, kis_app_secret: v })}
        secureTextEntry
      />
      <TextInput
        placeholder="KIS_ACCOUNT_NO"
        value={form.kis_account_no}
        onChangeText={(v) => setForm({ ...form, kis_account_no: v })}
      />
      <TextInput
        placeholder="KIS_ACCOUNT_PRODUCT_CODE"
        value={form.kis_account_product_code}
        onChangeText={(v) => setForm({ ...form, kis_account_product_code: v })}
      />
      <TextInput
        placeholder="TRADING_MODE (paper/live)"
        value={form.trading_mode}
        onChangeText={(v) => setForm({ ...form, trading_mode: v === "live" ? "live" : "paper" })}
      />
      <Button title="Save" onPress={save} />
      <Button title="Test Token Issuance" onPress={testConnection} />
      <Button title="Back to Dashboard" onPress={onBack} />
      <Text>{message}</Text>
    </SafeAreaView>
  );
}
