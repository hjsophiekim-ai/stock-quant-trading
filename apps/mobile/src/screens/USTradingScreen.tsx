import React, { useCallback, useEffect, useState } from "react";
import { Button, SafeAreaView, ScrollView, Text, TouchableOpacity, View } from "react-native";

import { getAuthState } from "../store/authStore";
import { STRATEGY_OPTIONS, type SessionState, type StrategyId, type TradingMarket } from "../types/trading";

type Props = {
  backendUrl: string;
  onOpenDashboard?: () => void;
  onOpenPerformance?: () => void;
};

type LogItem = { ts?: string; level?: string; message?: string };

type PositionItem = { symbol: string; quantity: number; average_price: number };

function text(v: unknown, fallback = "—"): string {
  if (v == null || v === "") return fallback;
  return String(v);
}

export default function USTradingScreen({ backendUrl, onOpenDashboard, onOpenPerformance }: Props) {
  const market: TradingMarket = "us";
  const [strategyId, setStrategyId] = useState<StrategyId>("swing_relaxed_v2");
  const [status, setStatus] = useState("stopped");
  const [sessionState, setSessionState] = useState<SessionState>("closed");
  const [strategyRunning, setStrategyRunning] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [positions, setPositions] = useState<PositionItem[]>([]);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [pnlText, setPnlText] = useState("");
  const [diagSummary, setDiagSummary] = useState("진단 정보 없음");

  const authHeaders = useCallback((): HeadersInit => {
    const token = getAuthState().accessToken;
    const h: Record<string, string> = {};
    if (token) h.Authorization = `Bearer ${token}`;
    return h;
  }, []);

  const paperApiUrl = useCallback(
    (path: string) => `${backendUrl}/api/paper-trading/${path}?market=${market}`,
    [backendUrl, market],
  );

  const refresh = useCallback(async () => {
    try {
      const headers = authHeaders();
      const [statusRes, posRes, logsRes, pnlRes, diagRes, dashRes] = await Promise.all([
        fetch(paperApiUrl("status"), { headers }),
        fetch(paperApiUrl("positions"), { headers }),
        fetch(paperApiUrl("logs"), { headers }),
        fetch(paperApiUrl("pnl"), { headers }),
        fetch(paperApiUrl("diagnostics"), { headers }),
        fetch(paperApiUrl("dashboard-data"), { headers }),
      ]);

      const statusData = await statusRes.json();
      const posData = await posRes.json();
      const logsData = await logsRes.json();
      const pnlData = await pnlRes.json();
      const diagData = await diagRes.json();
      const dashData = await dashRes.json();

      if (statusRes.ok) {
        setStatus(text(statusData.status, "stopped"));
        setStrategyRunning((statusData.strategy_id as string | null) ?? null);
      }
      if (posRes.ok) setPositions((posData.items ?? []) as PositionItem[]);
      if (logsRes.ok) setLogs((logsData.items ?? []) as LogItem[]);
      if (pnlRes.ok) {
        setPnlText(
          `당일 ${Number(pnlData.today_return_pct ?? 0).toFixed(2)}% · 누적 ${Number(pnlData.cumulative_return_pct ?? 0).toFixed(2)}% · 포지션 ${Number(pnlData.position_count ?? 0)}개`,
        );
      }

      const session =
        (statusData?.session_state as SessionState | undefined) ??
        (diagData?.session_state as SessionState | undefined) ??
        (dashData?.session_state as SessionState | undefined) ??
        "closed";
      setSessionState(session);

      const quote =
        diagData?.latest_quote ??
        dashData?.latest_quote ??
        dashData?.quote ??
        (diagData?.quotes && Array.isArray(diagData.quotes) ? diagData.quotes[0] : null);
      const bar =
        diagData?.latest_bar ??
        dashData?.latest_bar ??
        dashData?.bar ??
        (diagData?.bars && Array.isArray(diagData.bars) ? diagData.bars[0] : null);
      const quoteText = quote ? `quote: ${text((quote as Record<string, unknown>).symbol)} ${text((quote as Record<string, unknown>).price)}` : "quote: 없음";
      const barText = bar
        ? `bars: ${text((bar as Record<string, unknown>).time)} O:${text((bar as Record<string, unknown>).open)} H:${text((bar as Record<string, unknown>).high)} L:${text((bar as Record<string, unknown>).low)} C:${text((bar as Record<string, unknown>).close)}`
        : "bars: 없음";
      setDiagSummary(`${quoteText}\n${barText}`);
    } catch {
      setMessage("network error");
    }
  }, [authHeaders, paperApiUrl]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 15_000);
    return () => clearInterval(id);
  }, [refresh]);

  const start = async () => {
    setMessage("");
    try {
      const res = await fetch(paperApiUrl("start"), {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ strategy_id: strategyId, market }),
      });
      const data = (await res.json()) as { detail?: unknown };
      if (!res.ok) {
        setMessage(typeof data.detail === "string" ? data.detail : "US 세션 시작 실패");
        return;
      }
      setMessage("US Paper 세션 시작됨.");
      await refresh();
    } catch {
      setMessage("network error");
    }
  };

  const stop = async () => {
    try {
      const res = await fetch(paperApiUrl("stop"), {
        method: "POST",
        headers: authHeaders(),
      });
      const data = (await res.json()) as { detail?: unknown };
      if (!res.ok) {
        setMessage(typeof data.detail === "string" ? data.detail : "US 세션 중지 실패");
        return;
      }
      setMessage("US Paper 세션 중지됨.");
      await refresh();
    } catch {
      setMessage("network error");
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#f8fafc" }}>
      <ScrollView style={{ padding: 12 }}>
        <Text style={{ fontSize: 20, fontWeight: "bold", marginBottom: 6 }}>US Trading (Paper)</Text>
        <Text style={{ color: "#64748b", fontSize: 12, marginBottom: 10 }}>
          모든 호출은 market=us 로 전송됩니다.
        </Text>

        <View style={{ backgroundColor: "#eff6ff", padding: 10, borderRadius: 8, marginBottom: 10 }}>
          <Text style={{ fontWeight: "700" }}>상태: {status}</Text>
          <Text style={{ fontSize: 13, marginTop: 4 }}>전략: {strategyRunning ?? "—"}</Text>
          <Text style={{ fontSize: 13, marginTop: 4 }}>session_state: {sessionState}</Text>
        </View>

        <Text style={{ fontWeight: "600", marginBottom: 4 }}>미국 전략 선택</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", marginBottom: 10 }}>
          {STRATEGY_OPTIONS.map((option) => {
            const selected = option === strategyId;
            return (
              <TouchableOpacity
                key={option}
                onPress={() => setStrategyId(option)}
                style={{
                  backgroundColor: selected ? "#1d4ed8" : "#e2e8f0",
                  borderRadius: 999,
                  paddingVertical: 6,
                  paddingHorizontal: 10,
                  marginRight: 6,
                  marginBottom: 6,
                }}
              >
                <Text style={{ color: selected ? "#ffffff" : "#0f172a", fontSize: 12, fontWeight: "600" }}>{option}</Text>
              </TouchableOpacity>
            );
          })}
        </View>

        <Button title="US 자동매매 시작" onPress={start} />
        <View style={{ height: 8 }} />
        <Button title="US 자동매매 중지" onPress={stop} />
        <View style={{ height: 8 }} />
        <Button title="새로고침" onPress={refresh} />
        {message ? (
          <Text style={{ marginTop: 10, color: "#334155", lineHeight: 20 }} selectable>
            {message}
          </Text>
        ) : null}

        <Text style={{ marginTop: 16, fontWeight: "bold" }}>포지션</Text>
        {positions.length === 0 ? (
          <Text style={{ color: "#94a3b8", marginTop: 4 }}>없음</Text>
        ) : (
          positions.map((p) => (
            <Text key={p.symbol} style={{ marginTop: 4 }}>
              {p.symbol} qty={p.quantity} avg={p.average_price}
            </Text>
          ))
        )}

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>손익 요약</Text>
        <Text style={{ marginTop: 4, color: "#475569" }}>{pnlText || "—"}</Text>

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>Quote / Bars 진단 요약</Text>
        <Text style={{ marginTop: 4, color: "#334155", lineHeight: 18 }}>{diagSummary}</Text>

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>최근 로그</Text>
        {logs.slice(0, 25).map((l, idx) => (
          <Text key={idx} style={{ fontSize: 11, marginTop: 4, color: l.level === "error" ? "#b91c1c" : "#334155" }}>
            [{l.level}] {l.message}
          </Text>
        ))}

        <View style={{ marginTop: 20, marginBottom: 24 }}>
          {onOpenDashboard ? (
            <TouchableOpacity onPress={onOpenDashboard} style={{ marginBottom: 8 }}>
              <Text style={{ color: "#2563eb", fontWeight: "700" }}>→ 운영 대시보드</Text>
            </TouchableOpacity>
          ) : null}
          {onOpenPerformance ? (
            <TouchableOpacity onPress={onOpenPerformance}>
              <Text style={{ color: "#2563eb", fontWeight: "700" }}>→ 성과 화면</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
