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

  return (
    <SafeAreaView>
      <Text>Mobile Login</Text>
      <TextInput placeholder="Email" value={email} onChangeText={setEmail} autoCapitalize="none" />
      <TextInput placeholder="Password" value={password} onChangeText={setPassword} secureTextEntry />
      <Button title="Login" onPress={onLogin} />
      <Text>{message}</Text>
    </SafeAreaView>
  );
}
