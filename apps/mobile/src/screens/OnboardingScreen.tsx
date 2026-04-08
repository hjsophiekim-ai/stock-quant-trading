import React from "react";
import { Button, SafeAreaView, ScrollView, Text, View } from "react-native";

import { setOnboardingDone } from "../lib/session";

type Props = {
  onComplete: () => void;
};

export default function OnboardingScreen({ onComplete }: Props) {
  const finish = async () => {
    await setOnboardingDone();
    onComplete();
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#0f172a" }}>
      <ScrollView contentContainerStyle={{ padding: 20 }}>
        <Text style={{ color: "#f8fafc", fontSize: 22, fontWeight: "700", marginBottom: 12 }}>
          Stock Quant 시작하기
        </Text>
        <Text style={{ color: "#cbd5e1", marginBottom: 10, lineHeight: 22 }}>
          1. 서버 주소는 앱에 기본 설정되어 있습니다. (별도 입력 불필요)
        </Text>
        <Text style={{ color: "#cbd5e1", marginBottom: 10, lineHeight: 22 }}>
          2. 회원가입 후 로그인하면 바로 대시보드로 이동합니다.
        </Text>
        <Text style={{ color: "#cbd5e1", marginBottom: 10, lineHeight: 22 }}>
          3. 한국투자 API 키는 서버에만 암호화 저장됩니다. 앱에 키를 저장하지 않습니다.
        </Text>
        <Text style={{ color: "#94a3b8", marginBottom: 20, fontSize: 12, lineHeight: 18 }}>
          개발 빌드에서만 이 화면이 보입니다. Android 배포본(production)은 로그인 화면부터 시작합니다.
        </Text>
        <View style={{ marginTop: 8 }}>
          <Button title="계속" onPress={() => void finish()} color="#38bdf8" />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
