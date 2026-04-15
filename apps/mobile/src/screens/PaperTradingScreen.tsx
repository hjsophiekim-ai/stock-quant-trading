import React, { useCallback, useEffect, useState } from "react";
import { Picker } from "@react-native-picker/picker";
import { Button, SafeAreaView, ScrollView, Text, TouchableOpacity, View } from "react-native";

import { getAuthState } from "../store/authStore";
import {
  type DomesticStrategyId,
  type MarketId,
  DOMESTIC_STRATEGY_OPTIONS,
} from "../types/trading";

type Props = {
  backendUrl: string;
  onOpenDashboard?: () => void;
  onOpenPerformance?: () => void;
};

type LogItem = { ts?: string; level?: string; message?: string };

function formatApiErrorDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    try {
      return JSON.stringify(detail);
    } catch {
      return "입력 오류가 있습니다.";
    }
  }
  if (!detail || typeof detail !== "object") return "요청이 거절되었습니다.";
  const d = detail as Record<string, unknown>;
  const headMap: Record<string, string> = {
    PAPER_BALANCE_PREFLIGHT_FAILED: "잔고 preflight 실패",
    TOKEN_RATE_LIMIT_WAIT: "KIS 호출 제한",
    PAPER_TOKEN_NOT_READY: "토큰 재사용 실패",
  };
  let head = typeof d.code === "string" ? headMap[d.code] || "" : "";
  if (d.failure_kind === "invalid_mode") head = "모의 호스트가 아님";
  const msg = typeof d.message === "string" ? d.message.trim() : "";
  let body = "";
  if (msg) {
    body = msg;
  } else if (d.code) {
    body = `${String(d.code)} - ${msg || "(메시지 없음)"}`;
  } else {
    try {
      body = JSON.stringify(d);
    } catch {
      body = "상세를 표시할 수 없습니다.";
    }
  }
  let out = head && body.indexOf(head) === -1 ? `${head}\n${body}` : body || head || "요청이 거절되었습니다.";
  if (d.path) out += `\n· API 경로: ${String(d.path)}`;
  if (d.tr_id) out += `\n· TR ID: ${String(d.tr_id)}`;
  if (d.http_status != null && d.http_status !== "") out += `\n· HTTP 상태: ${String(d.http_status)}`;
  if (d.token_error_code) out += `\n· 토큰 오류코드: ${String(d.token_error_code)}`;
  if (d.failure_kind) out += `\n· 유형: ${String(d.failure_kind)}`;
  return out;
}

async function appendKisBalanceDebugLines(
  backendUrl: string,
  headers: HeadersInit,
  base: string,
): Promise<string> {
  try {
    const r = await fetch(`${backendUrl}/api/debug/kis-balance-check`, { headers });
    const dj = (await r.json()) as Record<string, unknown> | null;
    if (!dj) return base;
    if (dj.ok === true) {
      return `${base}\n\n[참고] 지금 잔고 진단은 성공했습니다. 방금 오류가 잠깐이었을 수 있어요. 잠시 뒤 다시 「시작」을 눌러 보세요.`;
    }
    const kind = String(dj.failure_kind || "");
    const lab =
      kind === "invalid_mode"
        ? "모의 호스트가 아님"
        : kind === "token_not_ready"
          ? "토큰 재사용 실패"
          : kind === "kis_error"
            ? "한투 API 응답 오류"
            : kind || "잔고 점검 실패";
    let extra = `\n\n[잔고 재점검] ${lab}`;
    if (dj.error) extra += `\n${String(dj.error)}`;
    if (dj.path) extra += `\n· API 경로: ${String(dj.path)}`;
    if (dj.tr_id) extra += `\n· TR ID: ${String(dj.tr_id)}`;
    if (dj.http_status != null && dj.http_status !== "") extra += `\n· HTTP 상태: ${String(dj.http_status)}`;
    return base + extra;
  } catch {
    return base;
  }
}

export default function PaperTradingScreen({ backendUrl, onOpenDashboard, onOpenPerformance }: Props) {
  const market: MarketId = "domestic";
  const [strategyId, setStrategyId] = useState<DomesticStrategyId>("swing_v1");
  const [status, setStatus] = useState("stopped");
  const [strategyRunning, setStrategyRunning] = useState<string | null>(null);
  const [failureStreak, setFailureStreak] = useState(0);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastTick, setLastTick] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [positions, setPositions] = useState<Array<{ symbol: string; quantity: number; average_price: number }>>([]);
  const [pnlText, setPnlText] = useState("");
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [canStart, setCanStart] = useState(false);
  const [brokerHint, setBrokerHint] = useState("");

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

  const checkBrokerGate = useCallback(async () => {
    const token = getAuthState().accessToken;
    if (!token) {
      setCanStart(false);
      setBrokerHint("로그인이 필요합니다.");
      return;
    }
    try {
      const r = await fetch(`${backendUrl}/api/broker-accounts/me/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (r.status === 404) {
        setCanStart(false);
        setBrokerHint("브로커 설정에서 모의(paper) 계정을 저장하고 연결 테스트를 통과하세요.");
        return;
      }
      const d = await r.json();
      if (!r.ok) {
        setCanStart(false);
        setBrokerHint(typeof d?.detail === "string" ? d.detail : "브로커 상태를 확인할 수 없습니다.");
        return;
      }
      if (d.trading_mode && String(d.trading_mode).toLowerCase() !== "paper") {
        setCanStart(false);
        setBrokerHint("Paper 자동매매는 브로커 trading_mode가 paper일 때만 시작할 수 있습니다. live는 차단됩니다.");
        return;
      }
      if (d.ok === true) {
        setCanStart(true);
        setBrokerHint("");
      } else {
        setCanStart(false);
        setBrokerHint(
          d.connection_message ||
            "연결 테스트에 성공한 뒤에만 시작할 수 있습니다. 브로커 설정에서 「연결 테스트」를 실행하세요.",
        );
      }
    } catch {
      setCanStart(false);
      setBrokerHint("네트워크 오류로 브로커 상태를 확인하지 못했습니다.");
    }
  }, [backendUrl]);

  const refresh = useCallback(async () => {
    await checkBrokerGate();
    try {
      const headers = authHeaders();
      const [statusRes, posRes, pnlRes, logsRes] = await Promise.all([
        fetch(paperApiUrl("status"), { headers }),
        fetch(paperApiUrl("positions"), { headers }),
        fetch(paperApiUrl("pnl"), { headers }),
        fetch(paperApiUrl("logs"), { headers }),
      ]);
      const statusData = await statusRes.json();
      const posData = await posRes.json();
      const pnlData = await pnlRes.json();
      const logsData = await logsRes.json();
      if (statusRes.ok) {
        setStatus(statusData.status ?? "stopped");
        setStrategyRunning(statusData.strategy_id ?? null);
        setFailureStreak(Number(statusData.failure_streak ?? 0));
        setLastError(statusData.last_error ?? null);
        setLastTick(statusData.last_tick_at ?? null);
      }
      if (posRes.ok) setPositions(posData.items ?? []);
      if (pnlRes.ok) {
        setPnlText(
          `당일수익률(틱기준) ${Number(pnlData.today_return_pct ?? 0).toFixed(2)}% · 누적 ${Number(pnlData.cumulative_return_pct ?? 0).toFixed(2)}% · 포지션 ${Number(pnlData.position_count ?? 0)}개`,
        );
      }
      if (logsRes.ok) setLogs((logsData.items ?? []) as LogItem[]);
    } catch {
      setMessage("network error");
    }
  }, [authHeaders, checkBrokerGate, paperApiUrl]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 15_000);
    return () => clearInterval(id);
  }, [refresh]);

  const start = async () => {
    if (!canStart) return;
    setMessage("");
    try {
      const res = await fetch(paperApiUrl("start"), {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ strategy_id: strategyId, market }),
      });
      const data = (await res.json()) as { detail?: unknown };
      if (!res.ok) {
        let shown = formatApiErrorDetail(data?.detail);
        shown = await appendKisBalanceDebugLines(backendUrl, authHeaders(), shown);
        setMessage(shown);
        return;
      }
      setMessage("Paper 세션 시작됨 (KIS 모의 주문 루프). 첫 틱까지 수십 초 걸릴 수 있습니다.");
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
        const shown = formatApiErrorDetail(data?.detail) || "중지 실패";
        setMessage(shown);
        return;
      }
      setMessage("Paper 세션 중지됨.");
      await refresh();
    } catch {
      setMessage("network error");
    }
  };

  const riskReset = async () => {
    try {
      const res = await fetch(paperApiUrl("risk-reset"), {
        method: "POST",
        headers: authHeaders(),
      });
      const data = (await res.json()) as { detail?: unknown };
      if (!res.ok) {
        const shown = formatApiErrorDetail(data?.detail) || "risk-reset 실패";
        setMessage(shown);
        return;
      }
      setMessage("risk_off 해제됨. 루프가 재개됩니다.");
      await refresh();
    } catch {
      setMessage("network error");
    }
  };

  const riskOff = status === "risk_off";

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#f8fafc" }}>
      <ScrollView style={{ padding: 12 }}>
        <Text style={{ fontSize: 20, fontWeight: "bold", marginBottom: 6 }}>Domestic Paper Trading (KIS 모의)</Text>
        <Text style={{ color: "#64748b", fontSize: 12, marginBottom: 10, lineHeight: 18 }}>
          앱에 저장한 <Text style={{ fontWeight: "700" }}>paper</Text> 브로커로만 동작합니다. live 계정·live 주문 경로는 사용하지
          않습니다. 전역 <Text style={{ fontWeight: "700" }}>/api/runtime-engine</Text> 과 별도 세션입니다.
        </Text>

        <View style={{ backgroundColor: "#eff6ff", padding: 10, borderRadius: 8, marginBottom: 10 }}>
          <Text style={{ fontWeight: "700" }}>상태: {status}</Text>
          <Text style={{ fontSize: 13, marginTop: 4 }}>전략: {strategyRunning ?? "—"}</Text>
          <Text style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>
            마지막 틱(UTC): {lastTick ?? "—"} · 실패 연속 {failureStreak}
          </Text>
          {lastError ? <Text style={{ fontSize: 12, color: "#b91c1c", marginTop: 6 }}>{lastError}</Text> : null}
        </View>

        {!canStart ? (
          <View
            style={{
              backgroundColor: "#fff7ed",
              borderColor: "#fdba74",
              borderWidth: 1,
              borderRadius: 8,
              padding: 10,
              marginBottom: 10,
            }}
          >
            <Text style={{ color: "#9a3412", fontSize: 13 }}>{brokerHint}</Text>
          </View>
        ) : null}

        {riskOff ? (
          <View style={{ backgroundColor: "#fef2f2", padding: 10, borderRadius: 8, marginBottom: 10 }}>
            <Text style={{ fontWeight: "700", color: "#991b1b", marginBottom: 6 }}>risk_off</Text>
            <Text style={{ fontSize: 13, color: "#7f1d1d", marginBottom: 8 }}>
              연속 오류 한도 초과. 원인 확인 후 risk-reset 또는 중지하세요.
            </Text>
            <Button title="risk-reset (소유자만)" onPress={riskReset} />
          </View>
        ) : null}

        <Text style={{ fontWeight: "600", marginBottom: 4 }}>전략 (국내 Paper)</Text>
        <View
          style={{
            borderWidth: 1,
            borderColor: "#cbd5e1",
            borderRadius: 8,
            marginBottom: 10,
            backgroundColor: "#fff",
            overflow: "hidden",
          }}
        >
          <Picker
            selectedValue={strategyId}
            onValueChange={(v) => setStrategyId(v as DomesticStrategyId)}
            mode="dropdown"
            style={{ width: "100%" }}
          >
            {DOMESTIC_STRATEGY_OPTIONS.map((id) => (
              <Picker.Item key={id} label={id} value={id} />
            ))}
          </Picker>
        </View>
        <Text style={{ fontSize: 12, color: "#64748b", marginBottom: 10 }}>
          데스크톱과 동일한 8종 전략입니다. 모든 호출은 쿼리·본문에 market=domestic 을 명시합니다.
        </Text>

        <Button title="모의 자동매매 시작" onPress={start} disabled={!canStart || riskOff} />
        <View style={{ height: 8 }} />
        <Button title="모의 자동매매 중지" onPress={stop} />
        <View style={{ height: 8 }} />
        <Button title="새로고침" onPress={refresh} />
        {message ? (
          <Text style={{ marginTop: 10, color: "#334155", lineHeight: 20 }} selectable>
            {message}
          </Text>
        ) : null}

        <Text style={{ marginTop: 16, fontWeight: "bold" }}>손익 요약 (마지막 틱)</Text>
        <Text style={{ fontSize: 13, color: "#475569", marginTop: 4 }}>{pnlText || "—"}</Text>

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>포지션 (마지막 틱 스냅샷)</Text>
        {positions.length === 0 ? (
          <Text style={{ color: "#94a3b8", marginTop: 4 }}>없음 — 틱 후 갱신</Text>
        ) : (
          positions.map((p) => (
            <Text key={p.symbol} style={{ marginTop: 4 }}>
              {p.symbol} qty={p.quantity} avg={p.average_price}
            </Text>
          ))
        )}

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>세션 로그</Text>
        {logs.slice(0, 25).map((l, idx) => (
          <Text key={idx} style={{ fontSize: 11, marginTop: 4, color: l.level === "error" ? "#b91c1c" : "#334155" }}>
            [{l.level}] {l.message}
          </Text>
        ))}

        <View style={{ marginTop: 20, marginBottom: 24 }}>
          <Text style={{ fontWeight: "600", marginBottom: 8 }}>결과 확인</Text>
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
