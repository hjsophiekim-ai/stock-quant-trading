import React, { useState } from "react";
import { Button, SafeAreaView, Switch, Text, TextInput, View } from "react-native";

import { clearPersistedAuth, savePersistedAuth } from "../lib/session";
import { setAuth } from "../store/authStore";

type Props = {
  backendUrl: string;
};

export default function LoginScreen({ backendUrl }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [remember, setRemember] = useState(true);

  const onLogin = async () => {
    setMessage("");
    try {
      const res = await fetch(`${backendUrl}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(typeof data?.detail === "string" ? data.detail : "로그인 실패");
        return;
      }
      const em = (data.user && data.user.email) || email.trim();
      setAuth({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        email: em,
      });
      if (remember) {
        await savePersistedAuth({
          accessToken: data.access_token,
          refreshToken: data.refresh_token,
          email: em,
          remember: true,
        });
      } else {
        await clearPersistedAuth();
      }
    } catch {
      setMessage("네트워크 오류 — 서버 상태 및 모바일 인터넷 연결을 확인하세요.");
    }
  };

  const onRegister = async () => {
    setMessage("");
    try {
      const res = await fetch(`${backendUrl}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim(),
          password,
          display_name: displayName.trim() || email.split("@")[0] || "user",
          role: "user",
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(typeof data?.detail === "string" ? data.detail : "회원가입 실패");
        return;
      }
      setMessage("가입 완료. 로그인을 눌러 대시보드로 이동하세요.");
    } catch {
      setMessage("네트워크 오류");
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, padding: 16, backgroundColor: "#fff" }}>
      <Text style={{ fontSize: 20, fontWeight: "700", marginBottom: 8 }}>로그인</Text>
      <Text style={{ color: "#64748b", marginBottom: 12, fontSize: 12 }}>
        서버: {backendUrl}
      </Text>
      <TextInput
        placeholder="이메일"
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        keyboardType="email-address"
        style={{ borderWidth: 1, borderColor: "#e2e8f0", padding: 10, marginBottom: 8, borderRadius: 6 }}
      />
      <TextInput
        placeholder="비밀번호"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        style={{ borderWidth: 1, borderColor: "#e2e8f0", padding: 10, marginBottom: 8, borderRadius: 6 }}
      />
      <TextInput
        placeholder="표시 이름 (회원가입 시)"
        value={displayName}
        onChangeText={setDisplayName}
        style={{ borderWidth: 1, borderColor: "#e2e8f0", padding: 10, marginBottom: 8, borderRadius: 6 }}
      />
      <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 12 }}>
        <Switch value={remember} onValueChange={setRemember} />
        <Text style={{ marginLeft: 8 }}>로그인 유지 (이 기기에 저장)</Text>
      </View>
      <Button title="로그인 후 대시보드로" onPress={() => void onLogin()} />
      <View style={{ height: 8 }} />
      <Button title="회원가입 (첫 실행)" onPress={() => void onRegister()} />
      {message ? (
        <Text style={{ marginTop: 12, color: message.includes("완료") ? "#15803d" : "#b91c1c" }}>{message}</Text>
      ) : null}
    </SafeAreaView>
  );
}
