import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

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

function parseApiDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const s = detail
      .map((x: { msg?: string; loc?: unknown[] }) => {
        const loc = Array.isArray(x?.loc) ? x.loc.filter((p) => p !== "body").join(".") : "";
        return loc ? `${loc}: ${x?.msg ?? ""}` : (x?.msg ?? "");
      })
      .filter(Boolean)
      .join("; ");
    return s || "요청을 처리할 수 없습니다.";
  }
  return "요청을 처리할 수 없습니다.";
}

export default function BrokerSettingsScreen({ backendUrl, onBack }: Props) {
  const [form, setForm] = useState<FormState>(initialForm);
  const [loadingAccount, setLoadingAccount] = useState(true);
  const [hasSavedAccount, setHasSavedAccount] = useState(false);
  const [maskedHint, setMaskedHint] = useState<{ key: string; account: string; product: string } | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<"unknown" | "success" | "failed">("unknown");
  const [connectionMessage, setConnectionMessage] = useState<string | null>(null);
  const [lastTestedAt, setLastTestedAt] = useState<string | null>(null);
  const [testBadge, setTestBadge] = useState<"idle" | "ok" | "fail">("idle");
  const [toast, setToast] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const auth = getAuthState();
  const authHeader = useMemo(() => {
    const h: Record<string, string> = {};
    if (auth.accessToken) h.Authorization = `Bearer ${auth.accessToken}`;
    return h;
  }, [auth.accessToken]);

  const showToast = useCallback((type: "ok" | "err", text: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ type, text });
    toastTimer.current = setTimeout(() => setToast(null), 3800);
  }, []);

  const isValid = useMemo(() => {
    return (
      form.kis_app_key.trim().length >= 8 &&
      form.kis_app_secret.trim().length >= 8 &&
      form.kis_account_no.trim().length >= 4 &&
      form.kis_account_product_code.trim().length >= 1
    );
  }, [form]);

  const refreshStatus = useCallback(async () => {
    try {
      const res = await fetch(`${backendUrl}/api/broker-accounts/me/status`, {
        headers: authHeader,
      });
      if (res.status === 404) {
        setHasSavedAccount(false);
        setConnectionStatus("unknown");
        setConnectionMessage(null);
        setLastTestedAt(null);
        return;
      }
      const data = await res.json();
      if (!res.ok) {
        showToast("err", parseApiDetail(data?.detail));
        return;
      }
      setHasSavedAccount(true);
      setConnectionStatus((data.connection_status as typeof connectionStatus) || "unknown");
      setConnectionMessage(data.connection_message ?? null);
      setLastTestedAt(typeof data.last_tested_at === "string" ? data.last_tested_at : null);
    } catch {
      showToast("err", "네트워크 오류 — 서버 주소와 실행 여부를 확인하세요.");
    }
  }, [authHeader, backendUrl, showToast]);

  const loadAccount = useCallback(async () => {
    setLoadingAccount(true);
    try {
      const res = await fetch(`${backendUrl}/api/broker-accounts/me`, { headers: authHeader });
      if (res.status === 404) {
        setHasSavedAccount(false);
        setMaskedHint(null);
        setForm(initialForm);
        await refreshStatus();
        return;
      }
      const data = await res.json();
      if (!res.ok) {
        showToast("err", parseApiDetail(data?.detail));
        return;
      }
      setHasSavedAccount(true);
      setMaskedHint({
        key: String(data.kis_app_key_masked ?? ""),
        account: String(data.kis_account_no_masked ?? ""),
        product: String(data.kis_account_product_code ?? ""),
      });
      setForm((f) => ({
        ...f,
        kis_account_product_code: String(data.kis_account_product_code ?? ""),
        trading_mode: data.trading_mode === "live" ? "live" : "paper",
      }));
      setConnectionStatus(data.connection_status ?? "unknown");
      setConnectionMessage(data.connection_message ?? null);
      setLastTestedAt(data.last_tested_at ? String(data.last_tested_at) : null);
    } catch {
      showToast("err", "계정 정보를 불러오지 못했습니다.");
    } finally {
      setLoadingAccount(false);
    }
  }, [authHeader, backendUrl, refreshStatus, showToast]);

  useEffect(() => {
    void loadAccount();
  }, [loadAccount]);

  const save = async () => {
    if (!isValid) {
      showToast("err", "앱키·시크릿(각 8자 이상), 계좌번호, 상품코드를 확인해주세요.");
      return;
    }
    try {
      const res = await fetch(`${backendUrl}/api/broker-accounts/me`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader },
        body: JSON.stringify({
          kis_app_key: form.kis_app_key.trim(),
          kis_app_secret: form.kis_app_secret.trim(),
          kis_account_no: form.kis_account_no.trim(),
          kis_account_product_code: form.kis_account_product_code.trim(),
          trading_mode: form.trading_mode,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        showToast("err", parseApiDetail(data?.detail));
        return;
      }
      setTestBadge("idle");
      showToast("ok", "브로커 정보가 서버에 암호화되어 저장되었습니다.");
      await loadAccount();
    } catch {
      showToast("err", "네트워크 오류");
    }
  };

  const testConnection = async () => {
    setTestBadge("idle");
    try {
      const res = await fetch(`${backendUrl}/api/broker-accounts/me/test-connection`, {
        method: "POST",
        headers: authHeader,
      });
      const data = await res.json();
      if (!res.ok) {
        setTestBadge("fail");
        showToast("err", parseApiDetail(data?.detail));
        return;
      }
      setTestBadge(data.ok ? "ok" : "fail");
      setConnectionStatus(data.status ?? "failed");
      setConnectionMessage(data.message ?? "");
      showToast(data.ok ? "ok" : "err", data.message ?? (data.ok ? "연결 성공" : "연결 실패"));
      await refreshStatus();
    } catch {
      setTestBadge("fail");
      showToast("err", "네트워크 오류");
    }
  };

  const confirmDelete = () => {
    Alert.alert(
      "브로커 계정 삭제",
      "서버에 저장된 한국투자 연동 정보를 삭제합니다. 계속할까요?",
      [
        { text: "취소", style: "cancel" },
        {
          text: "삭제",
          style: "destructive",
          onPress: () => void deleteAccount(),
        },
      ],
    );
  };

  const deleteAccount = async () => {
    try {
      const res = await fetch(`${backendUrl}/api/broker-accounts/me`, {
        method: "DELETE",
        headers: authHeader,
      });
      if (!res.ok) {
        const data = await res.json();
        showToast("err", parseApiDetail(data?.detail));
        return;
      }
      showToast("ok", "저장된 브로커 정보를 삭제했습니다.");
      setForm(initialForm);
      setHasSavedAccount(false);
      setMaskedHint(null);
      setTestBadge("idle");
      setConnectionStatus("unknown");
      setConnectionMessage(null);
      setLastTestedAt(null);
    } catch {
      showToast("err", "삭제 중 오류가 발생했습니다.");
    }
  };

  const badgeColor =
    testBadge === "ok" ? "#15803d" : testBadge === "fail" ? "#b91c1c" : "#64748b";
  const statusLabel =
    connectionStatus === "success" ? "연결됨" : connectionStatus === "failed" ? "실패" : "미확인";

  const card = {
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 14,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "#e2e8f0",
  } as const;

  if (loadingAccount) {
    return (
      <SafeAreaView style={{ flex: 1, justifyContent: "center", alignItems: "center" }}>
        <ActivityIndicator size="large" />
        <Text style={{ marginTop: 8, color: "#64748b" }}>브로커 설정 불러오는 중…</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#f8fafc" }}>
      <ScrollView style={{ flex: 1, padding: 16 }} keyboardShouldPersistTaps="handled">
        <Text style={{ fontSize: 22, fontWeight: "800", marginBottom: 4 }}>브로커 설정</Text>
        <Text style={{ color: "#64748b", fontSize: 13, marginBottom: 16 }}>
          한국투자증권 App Key·Secret·계좌 정보는 서버에만 암호화되어 저장됩니다.
        </Text>

        <View style={card}>
          <Text style={{ fontWeight: "700", marginBottom: 8 }}>현재 연결 상태</Text>
          <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            <View
              style={{
                paddingHorizontal: 10,
                paddingVertical: 4,
                borderRadius: 999,
                backgroundColor:
                  connectionStatus === "success" ? "#dcfce7" : connectionStatus === "failed" ? "#fee2e2" : "#f1f5f9",
              }}
            >
              <Text style={{ fontWeight: "700", color: "#0f172a" }}>{statusLabel}</Text>
            </View>
            {testBadge !== "idle" ? (
              <View style={{ paddingHorizontal: 10, paddingVertical: 4, borderRadius: 6, backgroundColor: "#f1f5f9" }}>
                <Text style={{ fontWeight: "600", color: badgeColor }}>
                  마지막 테스트: {testBadge === "ok" ? "성공" : "실패"}
                </Text>
              </View>
            ) : null}
          </View>
          {connectionMessage ? (
            <Text style={{ marginTop: 8, fontSize: 13, color: "#334155" }}>{connectionMessage}</Text>
          ) : null}
          <Text style={{ marginTop: 8, fontSize: 12, color: "#64748b" }}>
            마지막 테스트 시각: {lastTestedAt ? new Date(lastTestedAt).toLocaleString() : "—"}
          </Text>
        </View>

        {hasSavedAccount && maskedHint ? (
          <View style={{ ...card, backgroundColor: "#f0f9ff", borderColor: "#bae6fd" }}>
            <Text style={{ fontWeight: "700", marginBottom: 6 }}>저장된 계정 요약</Text>
            <Text style={{ fontSize: 13, color: "#0369a1" }}>앱키: {maskedHint.key}</Text>
            <Text style={{ fontSize: 13, color: "#0369a1" }}>계좌: {maskedHint.account}</Text>
            <Text style={{ fontSize: 13, color: "#0369a1" }}>상품코드: {maskedHint.product}</Text>
            <Text style={{ fontSize: 12, color: "#64748b", marginTop: 8 }}>
              수정 시 아래에 값을 다시 입력한 뒤 저장하세요.
            </Text>
          </View>
        ) : null}

        <View style={card}>
          <Text style={{ fontWeight: "600", marginBottom: 6 }}>App Key</Text>
          <TextInput
            placeholder="한국투자 Open API App Key"
            value={form.kis_app_key}
            onChangeText={(v) => setForm({ ...form, kis_app_key: v })}
            autoCapitalize="none"
            style={inputStyle}
          />
          <Text style={{ fontWeight: "600", marginBottom: 6, marginTop: 10 }}>App Secret</Text>
          <TextInput
            placeholder="한국투자 Open API App Secret"
            value={form.kis_app_secret}
            onChangeText={(v) => setForm({ ...form, kis_app_secret: v })}
            secureTextEntry
            autoCapitalize="none"
            style={inputStyle}
          />
          <Text style={{ fontWeight: "600", marginBottom: 6, marginTop: 10 }}>계좌번호</Text>
          <TextInput
            placeholder="숫자 8자리 또는 10자리"
            value={form.kis_account_no}
            onChangeText={(v) => setForm({ ...form, kis_account_no: v })}
            keyboardType="number-pad"
            style={inputStyle}
          />
          <Text style={{ fontWeight: "600", marginBottom: 6, marginTop: 10 }}>계좌상품코드</Text>
          <TextInput
            placeholder="숫자 2자리 (예: 01)"
            value={form.kis_account_product_code}
            onChangeText={(v) => setForm({ ...form, kis_account_product_code: v })}
            keyboardType="number-pad"
            maxLength={2}
            style={inputStyle}
          />

          <Text style={{ fontWeight: "600", marginTop: 14, marginBottom: 8 }}>Trading mode</Text>
          <View style={{ flexDirection: "row", gap: 10 }}>
            {(["paper", "live"] as const).map((m) => (
              <Pressable
                key={m}
                onPress={() => setForm({ ...form, trading_mode: m })}
                style={{
                  flex: 1,
                  paddingVertical: 12,
                  borderRadius: 8,
                  borderWidth: 2,
                  borderColor: form.trading_mode === m ? "#2563eb" : "#e2e8f0",
                  backgroundColor: form.trading_mode === m ? "#eff6ff" : "#fff",
                  alignItems: "center",
                }}
              >
                <Text style={{ fontWeight: "700" }}>{m === "paper" ? "모의투자 (paper)" : "실거래 (live)"}</Text>
              </Pressable>
            ))}
          </View>
          {form.trading_mode === "live" ? (
            <View
              style={{
                marginTop: 12,
                padding: 12,
                backgroundColor: "#fef2f2",
                borderRadius: 8,
                borderWidth: 1,
                borderColor: "#fecaca",
              }}
            >
              <Text style={{ fontWeight: "800", color: "#991b1b", marginBottom: 6 }}>실거래 모드 경고</Text>
              <Text style={{ fontSize: 13, color: "#7f1d1d", lineHeight: 20 }}>
                실계좌·실주문과 연결될 수 있습니다. 서버의 LIVE_TRADING 등 안전 플래그와 앱 승인 절차 없이는 주문이
                허용되지 않을 수 있으나, 키·계좌는 실거래용으로 취급됩니다. 기본은 모의투자(paper) 사용을 권장합니다.
              </Text>
            </View>
          ) : null}
        </View>

        <Pressable
          onPress={save}
          style={({ pressed }) => ({
            backgroundColor: pressed ? "#1d4ed8" : "#2563eb",
            paddingVertical: 14,
            borderRadius: 10,
            alignItems: "center",
            marginBottom: 10,
          })}
        >
          <Text style={{ color: "#fff", fontWeight: "800" }}>저장</Text>
        </Pressable>

        <Pressable
          onPress={testConnection}
          style={({ pressed }) => ({
            backgroundColor: pressed ? "#0f766e" : "#0d9488",
            paddingVertical: 14,
            borderRadius: 10,
            alignItems: "center",
            marginBottom: 10,
          })}
        >
          <Text style={{ color: "#fff", fontWeight: "800" }}>연결 테스트 (토큰 발급)</Text>
        </Pressable>

        <Pressable
          onPress={() => void refreshStatus()}
          style={({ pressed }) => ({
            backgroundColor: pressed ? "#e2e8f0" : "#f1f5f9",
            paddingVertical: 12,
            borderRadius: 10,
            alignItems: "center",
            marginBottom: 10,
          })}
        >
          <Text style={{ fontWeight: "700", color: "#334155" }}>상태 새로고침</Text>
        </Pressable>

        {hasSavedAccount ? (
          <Pressable onPress={confirmDelete} style={{ paddingVertical: 12, alignItems: "center", marginBottom: 24 }}>
            <Text style={{ color: "#b91c1c", fontWeight: "700" }}>저장된 브로커 정보 삭제</Text>
          </Pressable>
        ) : (
          <View style={{ height: 16 }} />
        )}

        <Pressable onPress={onBack} style={{ paddingVertical: 14, alignItems: "center", marginBottom: 32 }}>
          <Text style={{ color: "#2563eb", fontWeight: "700" }}>← 대시보드로</Text>
        </Pressable>
      </ScrollView>

      {toast ? (
        <View
          pointerEvents="none"
          style={{
            position: "absolute",
            left: 16,
            right: 16,
            bottom: 28,
            padding: 14,
            borderRadius: 10,
            backgroundColor: toast.type === "ok" ? "#14532d" : "#7f1d1d",
            shadowColor: "#000",
            shadowOpacity: 0.2,
            shadowRadius: 8,
            elevation: 4,
          }}
        >
          <Text style={{ color: "#fff", fontWeight: "700" }}>{toast.text}</Text>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

const inputStyle = {
  borderWidth: 1,
  borderColor: "#cbd5e1",
  borderRadius: 8,
  paddingHorizontal: 12,
  paddingVertical: 10,
  fontSize: 15,
  backgroundColor: "#fff",
};
