import React, { useCallback, useEffect, useState } from "react";
import {
  Button,
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";

import { getAuthState } from "../store/authStore";

type Props = {
  backendUrl: string;
  onOpenDashboard?: () => void;
  onOpenPerformance?: () => void;
};

type StrategyOption = "swing_v1" | "bull_focus_v1" | "defensive_v1";

type LogItem = { ts?: string; level?: string; message?: string };

function formatFetchFailure(err: unknown): string {
  if (err instanceof Error) {
    return `연결/런타임 오류: ${err.message}`;
  }
  return "연결 실패(네트워크/DNS/SSL 등) — 서버 주소를 확인하세요.";
}

export default function PaperTradingScreen({ backendUrl, onOpenDashboard, onOpenPerformance }: Props) {
  const [strategyId, setStrategyId] = useState<StrategyOption>("swing_v1");
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
  const [diagHint, setDiagHint] = useState("");
  const [backendVerLine, setBackendVerLine] = useState("");
  const [kisDetailBlock, setKisDetailBlock] = useState("");

  const authHeaders = useCallback((): HeadersInit => {
    const token = getAuthState().accessToken;
    const h: Record<string, string> = {};
    if (token) h.Authorization = `Bearer ${token}`;
    return h;
  }, []);

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
    } catch (e) {
      setCanStart(false);
      setBrokerHint(`브로커 상태 확인 실패 — ${formatFetchFailure(e)}`);
    }
  }, [backendUrl]);

  const refresh = useCallback(async () => {
    await checkBrokerGate();
    try {
      const headers = authHeaders();
      const [statusRes, posRes, pnlRes, logsRes, diagRes, verRes, runtimeRes] = await Promise.all([
        fetch(`${backendUrl}/api/paper-trading/status`),
        fetch(`${backendUrl}/api/paper-trading/positions`),
        fetch(`${backendUrl}/api/paper-trading/pnl`),
        fetch(`${backendUrl}/api/paper-trading/logs`),
        fetch(`${backendUrl}/api/paper-trading/diagnostics`, { headers }),
        fetch(`${backendUrl}/api/version`),
        fetch(`${backendUrl}/api/debug/runtime-info`),
      ]);
      const statusData = await statusRes.json();
      const posData = await posRes.json();
      const pnlData = await pnlRes.json();
      const logsData = await logsRes.json();
      const diagData = diagRes.ok ? await diagRes.json() : {};
      const verData = verRes.ok ? await verRes.json() : {};
      const runtimeData = runtimeRes.ok ? await runtimeRes.json() : {};
      if (statusRes.ok) {
        setStatus(statusData.status ?? "stopped");
        setStrategyRunning(statusData.strategy_id ?? null);
        setFailureStreak(Number(statusData.failure_streak ?? 0));
        const dg = (statusData as { diagnostics?: Record<string, unknown> }).diagnostics ?? diagData;
        const fk = String(dg.failure_kind ?? "");
        const prefix =
          fk === "rate_limit"
            ? "[KIS 초당한도] "
            : fk === "token_rate_limit"
              ? "[KIS 토큰 1분제한] "
              : fk === "token_failure"
                ? "[토큰] "
                : fk === "kis_business_error"
                  ? "[KIS 업무] "
                  : fk
                    ? `[${fk}] `
                    : "";
        const ep = dg.last_failed_endpoint ? ` · path=${String(dg.last_failed_endpoint)}` : "";
        const tr = dg.last_failed_tr_id ? ` · tr=${String(dg.last_failed_tr_id)}` : "";
        const err = statusData.last_error != null ? String(statusData.last_error) : null;
        setLastError(err ? `${prefix}${err}${ep}${tr}` : null);
        setLastTick(statusData.last_tick_at ?? null);
        const tok = dg.token_source != null ? String(dg.token_source) : "";
        const tickIv = dg.paper_tick_interval_sec != null ? `틱 ${String(dg.paper_tick_interval_sec)}s` : "";
        const bmode = dg.request_budget_mode != null ? `예산 ${String(dg.request_budget_mode)}` : "";
        const thr = dg.throttled_mode === true ? "KIS간격제한" : "";
        const uhit =
          typeof dg.universe_cache_hit === "boolean" ? (dg.universe_cache_hit ? "유니버스캐시HIT" : "유니버스캐시MISS") : "";
        const khit =
          typeof dg.kospi_cache_hit === "boolean" ? (dg.kospi_cache_hit ? "KOSPI캐시HIT" : "KOSPI캐시MISS") : "";
        const pskip =
          typeof dg.positions_refresh_skipped === "boolean"
            ? dg.positions_refresh_skipped
              ? "포지션스냅스킵"
              : "포지션스냅실행"
            : "";
        const sskip =
          typeof dg.portfolio_sync_skipped === "boolean"
            ? dg.portfolio_sync_skipped
              ? "포폴sync스킵"
              : "포폴sync실행"
            : "";
        const rateHint = fk === "rate_limit" ? "초당한도·백오프 " : "";
        const sb =
          dg.start_blocked_reason != null && String(dg.start_blocked_reason).length > 0
            ? `시작차단: ${String(dg.start_blocked_reason)}`
            : "";
        const tec = dg.token_error_code != null ? `token_err=${String(dg.token_error_code)}` : "";
        const parts = [tok && `토큰: ${tok}`, tickIv, bmode, thr, uhit, khit, pskip, sskip, rateHint, sb, tec].filter(
          Boolean,
        );
        setDiagHint(parts.join(" · "));
      }
      const dgx = statusRes.ok
        ? ((statusData as { diagnostics?: Record<string, unknown> }).diagnostics ?? diagData)
        : diagData;
      const shaFull = typeof dgx.backend_git_sha === "string" ? dgx.backend_git_sha : "";
      const vApp = typeof verData.app_version === "string" ? verData.app_version : "?";
      const vGit = typeof verData.git_sha === "string" ? verData.git_sha : "";
      setBackendVerLine(
        `${vApp} · git ${(shaFull || vGit).slice(0, 7) || "—"}` +
          (dgx.backend_build_time != null && String(dgx.backend_build_time)
            ? ` · build ${String(dgx.backend_build_time)}`
            : ""),
      );
      const kl: string[] = [];
      if (shaFull) kl.push(`paper_diag.git_sha: ${shaFull}`);
      if (runtimeData.backend_git_sha) kl.push(`runtime.git_sha: ${String(runtimeData.backend_git_sha)}`);
      if (runtimeData.backend_build_time) kl.push(`runtime.build_time: ${String(runtimeData.backend_build_time)}`);
      if (runtimeData.python_executable) kl.push(`python: ${String(runtimeData.python_executable)}`);
      const files = (runtimeData.module_files ?? {}) as Record<string, unknown>;
      if (files["app.clients.kis_client"]) kl.push(`module.kis_client: ${String(files["app.clients.kis_client"])}`);
      if (files["backend.app.engine.user_paper_loop"])
        kl.push(`module.user_paper_loop: ${String(files["backend.app.engine.user_paper_loop"])}`);
      if (files["app.brokers.kis_paper_broker"])
        kl.push(`module.kis_paper_broker: ${String(files["app.brokers.kis_paper_broker"])}`);
      if (dgx.last_failed_endpoint) kl.push(`path: ${String(dgx.last_failed_endpoint)}`);
      if (dgx.last_failed_tr_id) kl.push(`tr_id: ${String(dgx.last_failed_tr_id)}`);
      if (dgx.sanitized_params != null)
        kl.push(`sanitized_params:\n${JSON.stringify(dgx.sanitized_params, null, 2)}`);
      setKisDetailBlock(kl.join("\n"));
      if (posRes.ok) setPositions(posData.items ?? []);
      if (pnlRes.ok) {
        setPnlText(
          `당일수익률(틱기준) ${Number(pnlData.today_return_pct ?? 0).toFixed(2)}% · 누적 ${Number(pnlData.cumulative_return_pct ?? 0).toFixed(2)}% · 포지션 ${Number(pnlData.position_count ?? 0)}개`,
        );
      }
      if (logsRes.ok) setLogs((logsData.items ?? []) as LogItem[]);
      if (!statusRes.ok) {
        setMessage(
          statusRes.status >= 500
            ? `Paper 상태: 서버 오류 HTTP ${statusRes.status}`
            : `Paper 상태 조회 실패 HTTP ${statusRes.status}`,
        );
      } else {
        setMessage("");
      }
    } catch (e) {
      setMessage(formatFetchFailure(e));
    }
  }, [authHeaders, backendUrl, checkBrokerGate]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 15_000);
    return () => clearInterval(id);
  }, [refresh]);

  const start = async () => {
    if (!canStart) return;
    setMessage("");
    try {
      const res = await fetch(`${backendUrl}/api/paper-trading/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ strategy_id: strategyId }),
      });
      const data = await res.json();
      if (!res.ok) {
        const raw = data?.detail as
          | string
          | {
              message?: string;
              code?: string;
              token_error_code?: string;
              path?: string;
              tr_id?: string;
              failure_kind?: string;
            }
          | undefined;
        let line = "";
        if (raw && typeof raw === "object" && "message" in raw && raw.message) {
          const pre =
            raw.code === "TOKEN_RATE_LIMIT_WAIT"
              ? "[토큰 1분제한] "
              : raw.code === "PAPER_TOKEN_NOT_READY"
                ? "[토큰 준비 안 됨] "
                : raw.code === "PAPER_BALANCE_PREFLIGHT_FAILED"
                  ? "[balance preflight] "
                : "";
          const extra =
            (raw.path ? ` · path=${String(raw.path)}` : "") +
            (raw.tr_id ? ` · tr_id=${String(raw.tr_id)}` : "") +
            (raw.failure_kind ? ` · kind=${String(raw.failure_kind)}` : "");
          line =
            pre + String(raw.message) + (raw.token_error_code ? ` (${String(raw.token_error_code)})` : "") + extra;
        } else if (typeof raw === "string") {
          line = raw;
        }
        setMessage(
          res.status >= 500
            ? `서버 오류 HTTP ${res.status}${line ? " — " + line : ""}`
            : line || `시작 실패 HTTP ${res.status}`,
        );
        return;
      }
      setMessage("Paper 세션 시작됨 (KIS 모의 주문 루프). 첫 틱까지 수십 초 걸릴 수 있습니다.");
      await refresh();
    } catch (e) {
      setMessage(formatFetchFailure(e));
    }
  };

  const stop = async () => {
    try {
      const res = await fetch(`${backendUrl}/api/paper-trading/stop`, {
        method: "POST",
        headers: authHeaders(),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(typeof data?.detail === "string" ? data.detail : "stop failed");
        return;
      }
      setMessage("Paper 세션 중지됨.");
      await refresh();
    } catch (e) {
      setMessage(formatFetchFailure(e));
    }
  };

  const riskReset = async () => {
    try {
      const res = await fetch(`${backendUrl}/api/paper-trading/risk-reset`, {
        method: "POST",
        headers: authHeaders(),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(typeof data?.detail === "string" ? data.detail : "risk-reset failed");
        return;
      }
      setMessage("risk_off 해제됨. 루프가 재개됩니다.");
      await refresh();
    } catch (e) {
      setMessage(formatFetchFailure(e));
    }
  };

  const riskOff = status === "risk_off";

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#f8fafc" }}>
      <ScrollView style={{ padding: 12 }}>
        <Text style={{ fontSize: 20, fontWeight: "bold", marginBottom: 6 }}>Paper Trading (KIS 모의)</Text>
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
          {diagHint ? (
            <Text style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>{diagHint}</Text>
          ) : null}
          {backendVerLine ? (
            <Text style={{ fontSize: 10, color: "#64748b", marginTop: 6, fontFamily: "monospace" }}>
              백엔드: {backendVerLine}
            </Text>
          ) : null}
          {kisDetailBlock ? (
            <Text
              style={{
                fontSize: 10,
                color: "#0f172a",
                marginTop: 6,
                fontFamily: "monospace",
                backgroundColor: "#f1f5f9",
                padding: 8,
                borderRadius: 6,
              }}
            >
              {kisDetailBlock}
            </Text>
          ) : null}
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

        <Text style={{ fontWeight: "600", marginBottom: 4 }}>전략 ID</Text>
        <TextInput
          value={strategyId}
          onChangeText={(v) => setStrategyId((v as StrategyOption) || "swing_v1")}
          placeholder="swing_v1 | bull_focus_v1 | defensive_v1"
          style={{ borderWidth: 1, borderColor: "#cbd5e1", padding: 8, marginBottom: 10, borderRadius: 8 }}
        />

        <Button title="모의 자동매매 시작" onPress={start} disabled={!canStart || riskOff} />
        <View style={{ height: 8 }} />
        <Button title="모의 자동매매 중지" onPress={stop} />
        <View style={{ height: 8 }} />
        <Button title="새로고침" onPress={refresh} />
        {message ? <Text style={{ marginTop: 10, color: "#334155" }}>{message}</Text> : null}

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
