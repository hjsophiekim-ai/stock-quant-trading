import React, { useState } from "react";
import { Button, SafeAreaView, Text, TextInput } from "react-native";

import { setAuth } from "../store/authStore";

type Props = {
  backendUrl: string;
};

export default function LoginScreen({ backendUrl }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [displayName, setDisplayName] = useState("");

  const onLogin = async () => {
    try {
      const res = await fetch(`${backendUrl}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data?.detail ?? "Login failed");
        return;
      }
      setAuth({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        email,
      });
      setMessage("Login success");
    } catch {
      setMessage("Network error");
    }
  };

  const onRegister = async () => {
    try {
      const res = await fetch(`${backendUrl}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          display_name: displayName || email.split("@")[0] || "new-user",
          role: "user",
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data?.detail ?? "Register failed");
        return;
      }
      setMessage("회원가입 완료. 이제 Login 버튼을 눌러 로그인하세요.");
    } catch {
      setMessage("Network error");
    }
  };

  return (
    <SafeAreaView>
      <Text>Mobile Login</Text>
      <Text>첫 실행이면 Register 후 Login 순서로 진행하세요.</Text>
      <TextInput placeholder="Email" value={email} onChangeText={setEmail} autoCapitalize="none" />
      <TextInput placeholder="Password" value={password} onChangeText={setPassword} secureTextEntry />
      <TextInput placeholder="Display Name (optional)" value={displayName} onChangeText={setDisplayName} />
      <Button title="Register (First Run)" onPress={onRegister} />
      <Button title="Login" onPress={onLogin} />
      <Text>{message}</Text>
    </SafeAreaView>
  );
}
