import React, { useCallback, useEffect, useRef, useState } from "react";
import { Picker } from "@react-native-picker/picker";
import { Button, SafeAreaView, ScrollView, Text, TextInput, TouchableOpacity, View } from "react-native";

import { authFetch } from "../lib/authFetch";
import {
  type MarketId,
  type SessionState,
  type SymbolSearchMatch,
  type SymbolSearchResponse,
  type TradingLogItem,
  type TradingPositionItem,
  type USStrategyId,
  US_STRATEGY_OPTIONS,
} from "../types/trading";

type Props = {
  backendUrl: string;
  onOpenDashboard?: () => void;
  onOpenPerformance?: () => void;
};

function text(v: unknown, fallback = "—"): string {
  if (v == null || v === "") return fallback;
  return String(v);
}

const US_SESSION_LABELS: SessionState[] = ["premarket", "regular", "after_hours", "closed"];

function formatHttpDetail(detail: unknown, clientRequestStrategy?: string): string {
  const clientReq = clientRequestStrategy != null ? String(clientRequestStrategy).trim() : "";
  if (typeof detail === "string") return detail;
  if (!detail || typeof detail !== "object") return "요청이 거절되었습니다.";
  const d = detail as Record<string, unknown>;
  if (d.code === "FINAL_BETTING_DISABLED") {
    const echoReq =
      d.request_strategy_id != null && String(d.request_strategy_id).trim() !== ""
        ? String(d.request_strategy_id).trim()
        : clientReq;
    const eff = echoReq || clientReq;
    if (eff.toLowerCase() !== "final_betting_v1") {
      const parts = [
        "⚠ 요청/응답 strategy 불일치 의심 (US에서 FINAL_BETTING_DISABLED)",
        `클라이언트 strategy_id: ${clientReq || "(없음)"}`,
        `서버 detail.request_strategy_id: ${d.request_strategy_id != null ? String(d.request_strategy_id) : "(없음)"}`,
      ];
      if (d.paper_start_diagnostics && typeof d.paper_start_diagnostics === "object") {
        try {
          parts.push(`paper_start_diagnostics: ${JSON.stringify(d.paper_start_diagnostics).slice(0, 800)}`);
        } catch {
          /* ignore */
        }
      }
      return parts.join("\n");
    }
    const parts: string[] = [
      typeof d.message === "string" ? d.message : "FINAL_BETTING_DISABLED",
      "요청 strategy_id: final_betting_v1 (확인됨)",
    ];
    if (typeof d.root_cause === "string") parts.push(`원인 코드(root_cause): ${d.root_cause}`);
    if (typeof d.deployment_fix_ko === "string" && d.deployment_fix_ko.trim()) parts.push(d.deployment_fix_ko.trim());
    parts.push(d.strategy_implemented === true ? "전략 코드: 구현됨" : "전략 코드: 확인 필요");
    parts.push(
      d.settings_not_reflected === true
        ? "원인 추정: 서버 설정 캐시 불일치(fresh Settings vs get_settings)"
        : "원인 추정: 환경변수 PAPER_FINAL_BETTING_ENABLED 등이 false/미설정",
    );
    if (d.final_betting) {
      try {
        parts.push(JSON.stringify(d.final_betting).slice(0, 1200));
      } catch {
        /* ignore */
      }
    }
    return parts.join("\n");
  }
  try {
    return JSON.stringify(detail).slice(0, 1500);
  } catch {
    return "요청이 거절되었습니다.";
  }
}

function normalizeUsSessionState(raw: unknown): SessionState {
  const s = String(raw || "")
    .trim()
    .toLowerCase()
    .replace(/-/g, "_");
  if (US_SESSION_LABELS.includes(s as SessionState)) return s as SessionState;
  if (s === "pre_open" || s === "preopen" || s === "pre_market") return "premarket";
  if (s === "afterhours" || s === "after") return "after_hours";
  return "closed";
}

export default function USTradingScreen({ backendUrl, onOpenDashboard, onOpenPerformance }: Props) {
  const market: MarketId = "us";
  const [strategyId, setStrategyId] = useState<USStrategyId>("us_swing_relaxed_v1");
  const [status, setStatus] = useState("stopped");
  const [sessionState, setSessionState] = useState<SessionState>("closed");
  const [strategyRunning, setStrategyRunning] = useState<string | null>(null);
  const [manualOverride, setManualOverride] = useState(false);
  const [message, setMessage] = useState("");
  const [positions, setPositions] = useState<TradingPositionItem[]>([]);
  const [logs, setLogs] = useState<TradingLogItem[]>([]);
  const [pnlText, setPnlText] = useState("");
  const [diagSummary, setDiagSummary] = useState("진단 정보 없음");
  const [usPaperCapable, setUsPaperCapable] = useState(true);
  const [capBanner, setCapBanner] = useState<string | null>(null);
  const [capRawJson, setCapRawJson] = useState<string>("(capabilities 로드 전)");
  const [versionMeta, setVersionMeta] = useState("빌드 정보 로딩…");
  const [lastStartPayload, setLastStartPayload] = useState("(아직 없음)");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SymbolSearchMatch[]>([]);
  const [searchBanner, setSearchBanner] = useState<string | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [selectedSymbolDiag, setSelectedSymbolDiag] = useState("종목을 선택하면 quote/status 진단을 표시합니다.");
  const lastDiagRef = useRef<Record<string, unknown>>({});
  const lastDashRef = useRef<Record<string, unknown>>({});

  const paperApiUrl = useCallback(
    (path: string) => `${backendUrl}/api/paper-trading/${path}?market=${market}`,
    [backendUrl, market],
  );

  const loadCapabilities = useCallback(async () => {
    try {
      const r = await fetch(`${backendUrl}/api/paper-trading/capabilities`);
      if (!r.ok) {
        setUsPaperCapable(false);
        setCapRawJson(`HTTP ${r.status} (capabilities)`);
        setCapBanner("capabilities API 오류 — US Paper 시작이 비활성화됩니다.");
        return;
      }
      const d = (await r.json()) as { us_paper_supported?: boolean };
      try {
        setCapRawJson(JSON.stringify(d, null, 2));
      } catch {
        setCapRawJson(String(d));
      }
      const ok = d.us_paper_supported !== false;
      setUsPaperCapable(ok);
      setCapBanner(ok ? null : "서버가 US Paper 를 지원하지 않는다고 응답했습니다(us_paper_supported=false).");
    } catch {
      setUsPaperCapable(false);
      setCapBanner("capabilities 로드 실패 — 네트워크를 확인하세요.");
      setCapRawJson("(capabilities fetch error)");
    }
  }, [backendUrl]);

  const updateSymbolDiagnostic = useCallback(
    (symbol: string | null, diagData: Record<string, unknown>, dashData: Record<string, unknown>) => {
      if (!symbol) {
        setSelectedSymbolDiag("종목을 선택하면 quote/status 진단을 표시합니다.");
        return;
      }
      const quoteItems = [
        ...(Array.isArray(diagData?.quotes) ? (diagData.quotes as Record<string, unknown>[]) : []),
        ...(Array.isArray(dashData?.quotes) ? (dashData.quotes as Record<string, unknown>[]) : []),
      ];
      const barItems = [
        ...(Array.isArray(diagData?.bars) ? (diagData.bars as Record<string, unknown>[]) : []),
        ...(Array.isArray(dashData?.bars) ? (dashData.bars as Record<string, unknown>[]) : []),
      ];
      const quote =
        quoteItems.find((q) => String(q?.symbol || "").toUpperCase() === symbol.toUpperCase()) ??
        (diagData?.latest_quote as Record<string, unknown> | undefined) ??
        (dashData?.latest_quote as Record<string, unknown> | undefined);
      const bar =
        barItems.find((b) => String(b?.symbol || "").toUpperCase() === symbol.toUpperCase()) ??
        (diagData?.latest_bar as Record<string, unknown> | undefined) ??
        (dashData?.latest_bar as Record<string, unknown> | undefined);

      const quoteText = quote
        ? `quote: ${text(quote.symbol)} ${text(quote.price)}`
        : `quote: ${symbol} 데이터 없음`;
      const barText = bar
        ? `bars: ${text(bar.time)} O:${text(bar.open)} H:${text(bar.high)} L:${text(bar.low)} C:${text(bar.close)}`
        : "bars: 데이터 없음";
      setSelectedSymbolDiag(`${quoteText}\n${barText}`);
    },
    [],
  );

  const refresh = useCallback(async () => {
    try {
      const [statusRes, posRes, logsRes, pnlRes, diagRes, dashRes] = await Promise.all([
        authFetch(backendUrl, paperApiUrl("status")),
        authFetch(backendUrl, paperApiUrl("positions")),
        authFetch(backendUrl, paperApiUrl("logs")),
        authFetch(backendUrl, paperApiUrl("pnl")),
        authFetch(backendUrl, paperApiUrl("diagnostics")),
        authFetch(backendUrl, paperApiUrl("dashboard-data")),
      ]);

      const statusData = (await statusRes.json()) as Record<string, unknown>;
      const posData = (await posRes.json()) as Record<string, unknown>;
      const logsData = (await logsRes.json()) as Record<string, unknown>;
      const pnlData = (await pnlRes.json()) as Record<string, unknown>;
      const diagData = (await diagRes.json()) as Record<string, unknown>;
      const dashData = (await dashRes.json()) as Record<string, unknown>;

      lastDiagRef.current = diagData;
      lastDashRef.current = dashData;

      const sha = String(statusData.backend_git_sha || diagData.backend_git_sha || "—");
      const bt = String(statusData.backend_build_time || diagData.backend_build_time || "—");
      const sid = statusData.strategy_id != null ? String(statusData.strategy_id) : "—";
      const pm = statusData.paper_market != null ? String(statusData.paper_market) : String(diagData.paper_market ?? "—");
      const rm =
        statusData.requested_market != null && String(statusData.requested_market) !== ""
          ? String(statusData.requested_market)
          : market;
      const fb =
        statusData.final_betting_enabled_effective !== undefined && statusData.final_betting_enabled_effective !== null
          ? String(statusData.final_betting_enabled_effective)
          : diagData.final_betting_enabled_effective != null
            ? String(diagData.final_betting_enabled_effective)
            : "—";
      const mm = statusData.market_mismatch === true ? "YES" : "no";
      setVersionMeta(
        `backend_git_sha: ${sha}\nbackend_build_time: ${bt}\nstatus.strategy_id: ${sid}\nrequested_market: ${rm}\nsession paper_market: ${pm}\nfinal_betting_enabled_effective: ${fb}\nmarket_mismatch: ${mm}`,
      );

      if (statusRes.ok) {
        setStatus(text(statusData.status, "stopped"));
        setStrategyRunning((statusData.strategy_id as string | null) ?? null);
        setManualOverride(Boolean(statusData.manual_override_enabled));
      }
      if (posRes.ok) setPositions((posData.items ?? []) as TradingPositionItem[]);
      if (logsRes.ok) setLogs((logsData.items ?? []) as TradingLogItem[]);
      if (pnlRes.ok) {
        setPnlText(
          `당일 ${Number(pnlData.today_return_pct ?? 0).toFixed(2)}% · 누적 ${Number(pnlData.cumulative_return_pct ?? 0).toFixed(2)}% · 포지션 ${Number(pnlData.position_count ?? 0)}개`,
        );
      }

      const rawSession =
        statusData.session_state ??
        diagData.session_state ??
        dashData.session_state ??
        (statusData as { tick_report?: { krx_session_state?: string } }).tick_report?.krx_session_state;
      setSessionState(normalizeUsSessionState(rawSession));

      const fallbackQuote = (diagData?.latest_quote ?? dashData?.latest_quote ?? dashData?.quote) as
        | Record<string, unknown>
        | undefined;
      const fallbackBar = (diagData?.latest_bar ?? dashData?.latest_bar ?? dashData?.bar) as
        | Record<string, unknown>
        | undefined;
      const quoteText = fallbackQuote ? `quote: ${text(fallbackQuote.symbol)} ${text(fallbackQuote.price)}` : "quote: 없음";
      const barText = fallbackBar
        ? `bars: ${text(fallbackBar.time)} O:${text(fallbackBar.open)} H:${text(fallbackBar.high)} L:${text(fallbackBar.low)} C:${text(fallbackBar.close)}`
        : "bars: 없음";
      setDiagSummary(`${quoteText}\n${barText}`);
      updateSymbolDiagnostic(selectedSymbol, diagData, dashData);
    } catch (e) {
      if (e instanceof Error && e.message === "SESSION_EXPIRED") {
        setMessage("세션이 만료되었습니다. 다시 로그인해 주세요.");
        return;
      }
      setMessage("network error");
    }
  }, [authHeaders, market, paperApiUrl, selectedSymbol, updateSymbolDiagnostic]);

  useEffect(() => {
    void loadCapabilities();
  }, [loadCapabilities]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 15_000);
    return () => clearInterval(id);
  }, [refresh]);

  const start = async () => {
    if (!usPaperCapable) return;
    setMessage("");
    const sid = strategyId;
    const body = JSON.stringify({ strategy_id: sid, market });
    setLastStartPayload(`start payload: ${body}`);
    try {
      const res = await authFetch(backendUrl, paperApiUrl("start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
      const data = (await res.json()) as { detail?: unknown; start_request_echo?: unknown };
      if (!res.ok) {
        let shown = formatHttpDetail(data.detail, sid);
        const dr = data.detail as Record<string, unknown> | undefined;
        shown += "\n\n--- HTTP 오류 메타 ---\n";
        if (dr && typeof dr === "object") {
          if (dr.code != null) shown += `response detail.code: ${String(dr.code)}\n`;
          if (dr.message != null) shown += `response detail.message: ${String(dr.message)}\n`;
          const psd = dr.paper_start_diagnostics as Record<string, unknown> | undefined;
          if (psd && typeof psd === "object") {
            shown += `controller paper_start_diagnostics.strategy_id: ${String(psd.strategy_id ?? "")}\n`;
            shown += `controller paper_start_diagnostics.effective_market: ${String(psd.effective_market ?? "")}\n`;
          }
        }
        shown += `last start payload (UI): ${body}\n`;
        setMessage(shown);
        return;
      }
      const echo = data.start_request_echo != null ? JSON.stringify(data.start_request_echo) : "";
      setLastStartPayload(`start payload: ${body}${echo ? `\n서버 echo: ${echo}` : ""}`);
      setMessage("US Paper 세션 시작됨.");
      await refresh();
    } catch (e) {
      if (e instanceof Error && e.message === "SESSION_EXPIRED") {
        setMessage("세션이 만료되었습니다. 다시 로그인해 주세요.");
        return;
      }
      setMessage("network error");
    }
  };

  const stop = async () => {
    try {
      const res = await authFetch(backendUrl, paperApiUrl("stop"), { method: "POST" });
      const data = (await res.json()) as { detail?: unknown };
      if (!res.ok) {
        setMessage(typeof data.detail === "string" ? data.detail : "US 세션 중지 실패");
        return;
      }
      setMessage("US Paper 세션 중지됨.");
      await refresh();
    } catch (e) {
      if (e instanceof Error && e.message === "SESSION_EXPIRED") {
        setMessage("세션이 만료되었습니다. 다시 로그인해 주세요.");
        return;
      }
      setMessage("network error");
    }
  };

  const toggleManualOverride = async () => {
    try {
      const res = await authFetch(backendUrl, paperApiUrl("manual-override-toggle"), { method: "POST" });
      const data = (await res.json()) as { detail?: unknown; manual_override_enabled?: boolean };
      if (!res.ok) {
        setMessage(typeof data.detail === "string" ? data.detail : "수동 재개 토글 실패");
        return;
      }
      setMessage(Boolean(data.manual_override_enabled) ? "수동 재개 ON (리스크 차단 우회)." : "수동 재개 OFF (기본 차단 복구).");
      await refresh();
    } catch (e) {
      if (e instanceof Error && e.message === "SESSION_EXPIRED") {
        setMessage("세션이 만료되었습니다. 다시 로그인해 주세요.");
        return;
      }
      setMessage("network error");
    }
  };

  const searchUSSymbols = async () => {
    const q = searchQuery.trim();
    setSearchBanner(null);
    if (!q) {
      setSearchResults([]);
      return;
    }
    try {
      const u = new URL(`${backendUrl}/api/stocks/search-by-symbol`);
      u.searchParams.set("q", q);
      u.searchParams.set("limit", "25");
      u.searchParams.set("market", market);
      const res = await authFetch(backendUrl, u.toString());
      const data = (await res.json()) as SymbolSearchResponse;
      if (!res.ok) {
        setSearchBanner("미국 종목 검색 API 오류 — 서버 응답을 확인하세요.");
        setSearchResults([]);
        return;
      }
      if (data.market !== "us") {
        setSearchBanner(
          "미국 종목 검색 API 미구현 또는 레거시 서버입니다. 응답이 market=us 가 아니므로 국내 목록을 표시하지 않습니다.",
        );
        setSearchResults([]);
        return;
      }
      if (data.us_search_supported !== true) {
        setSearchBanner(
          data.us_search_supported === false
            ? "미국 종목 검색 API 미구현 — 국내 25종 fallback 을 사용하지 않습니다."
            : "미국 종목 검색이 아직 활성화되지 않았습니다(us_search_supported≠true).",
        );
        setSearchResults([]);
        return;
      }
      const matches = data.matches ?? [];
      setSearchResults(matches);
      if (matches.length === 0) {
        setSearchBanner("검색 결과 없음.");
      }
    } catch (e) {
      if (e instanceof Error && e.message === "SESSION_EXPIRED") {
        setMessage("세션이 만료되었습니다. 다시 로그인해 주세요.");
        return;
      }
      setMessage("network error");
    }
  };

  const onPickSearchResult = (symbol: string) => {
    setSelectedSymbol(symbol);
    updateSymbolDiagnostic(symbol, lastDiagRef.current, lastDashRef.current);
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#f8fafc" }}>
      <ScrollView style={{ padding: 12 }}>
        <Text style={{ fontSize: 20, fontWeight: "bold", marginBottom: 6 }}>US Trading (Paper)</Text>
        <Text style={{ color: "#64748b", fontSize: 12, marginBottom: 10 }}>
          모든 paper API 호출에 <Text style={{ fontWeight: "700" }}>market=us</Text> 쿼리를 붙입니다. 세션도{" "}
          <Text style={{ fontWeight: "700" }}>market=us</Text> 로 시작해야 합니다.
        </Text>

        <View style={{ backgroundColor: "#f0fdf4", padding: 10, borderRadius: 8, marginBottom: 10, borderWidth: 1, borderColor: "#86efac" }}>
          <Text style={{ fontWeight: "700", marginBottom: 4 }}>빌드·세션 진단 (스크린샷용)</Text>
          <Text style={{ fontSize: 11, color: "#0f172a", lineHeight: 18 }} selectable>
            {versionMeta}
          </Text>
        </View>
        <View style={{ backgroundColor: "#faf5ff", padding: 10, borderRadius: 8, marginBottom: 10, borderWidth: 1, borderColor: "#e9d5ff" }}>
          <Text style={{ fontWeight: "700", marginBottom: 4 }}>capabilities (raw)</Text>
          <Text style={{ fontSize: 10, color: "#475569", lineHeight: 16, fontFamily: "monospace" }} selectable>
            {capRawJson.slice(0, 2500)}
          </Text>
        </View>
        <View style={{ backgroundColor: "#faf5ff", padding: 10, borderRadius: 8, marginBottom: 10, borderWidth: 1, borderColor: "#e9d5ff" }}>
          <Text style={{ fontWeight: "700", marginBottom: 4 }}>마지막 US Paper 시작 요청</Text>
          <Text style={{ fontSize: 11, color: "#334155", lineHeight: 18 }} selectable>
            {lastStartPayload}
          </Text>
        </View>

        <View style={{ backgroundColor: "#eff6ff", padding: 10, borderRadius: 8, marginBottom: 10 }}>
          <Text style={{ fontWeight: "700" }}>상태: {status}</Text>
          <Text style={{ fontSize: 13, marginTop: 4 }}>전략: {strategyRunning ?? "—"}</Text>
          <Text style={{ fontSize: 13, marginTop: 4 }}>
            session_state (US 라벨): <Text style={{ fontWeight: "700" }}>{sessionState}</Text>
          </Text>
          <Text style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
            premarket / regular / after_hours / closed — 틱 리포트의 us_session_state 를 표시합니다.
          </Text>
          <Text style={{ fontSize: 12, marginTop: 4, color: manualOverride ? "#b91c1c" : "#64748b" }}>
            수동 재개 토글: {manualOverride ? "ON" : "OFF"}
          </Text>
        </View>

        {!usPaperCapable && capBanner ? (
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
            <Text style={{ fontWeight: "700", color: "#9a3412", marginBottom: 4 }}>US Paper 비활성</Text>
            <Text style={{ fontSize: 13, color: "#9a3412" }}>{capBanner}</Text>
          </View>
        ) : null}

        <Text style={{ fontWeight: "600", marginBottom: 4 }}>미국 전략 선택</Text>
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
            enabled={usPaperCapable}
            selectedValue={strategyId}
            onValueChange={(v) => setStrategyId(v as USStrategyId)}
            mode="dropdown"
            style={{ width: "100%" }}
          >
            {US_STRATEGY_OPTIONS.map((id) => (
              <Picker.Item key={id} label={id} value={id} />
            ))}
          </Picker>
        </View>

        <Button title="US 자동매매 시작" onPress={start} disabled={!usPaperCapable} />
        <View style={{ height: 8 }} />
        <Button title="US 자동매매 중지" onPress={stop} />
        <View style={{ height: 8 }} />
        <Button title={manualOverride ? "수동 재개 토글 OFF" : "수동 재개 토글 ON"} onPress={toggleManualOverride} />
        <View style={{ height: 8 }} />
        <Button title="새로고침" onPress={refresh} />
        {message ? (
          <Text style={{ marginTop: 10, color: "#334155", lineHeight: 20 }} selectable>
            {message}
          </Text>
        ) : null}

        <Text style={{ marginTop: 16, fontWeight: "bold" }}>미국 종목 검색</Text>
        <View style={{ marginTop: 6, marginBottom: 10 }}>
          <TextInput
            value={searchQuery}
            onChangeText={setSearchQuery}
            placeholder="예: NVDA, AAPL"
            autoCapitalize="characters"
            style={{ borderWidth: 1, borderColor: "#cbd5e1", padding: 8, borderRadius: 8, backgroundColor: "#fff" }}
          />
          <View style={{ height: 8 }} />
          <Button title="미국 종목 검색" onPress={searchUSSymbols} />
          {searchBanner ? (
            <Text style={{ fontSize: 12, color: "#b45309", marginTop: 8, lineHeight: 18 }}>{searchBanner}</Text>
          ) : (
            <Text style={{ fontSize: 12, color: "#64748b", marginTop: 6 }}>
              `/api/stocks/search-by-symbol?market=us` — KIS search-info 기반.
            </Text>
          )}
        </View>
        {searchResults.length === 0 && !searchBanner ? (
          <Text style={{ fontSize: 12, color: "#94a3b8" }}>검색 전입니다.</Text>
        ) : null}
        {searchResults.slice(0, 20).map((item, idx) => {
          const symbol = String(item.symbol || "");
          const selected = symbol.toUpperCase() === String(selectedSymbol || "").toUpperCase();
          return (
            <TouchableOpacity
              key={`${symbol}-${idx}`}
              onPress={() => onPickSearchResult(symbol)}
              style={{
                borderWidth: 1,
                borderColor: selected ? "#1d4ed8" : "#cbd5e1",
                borderRadius: 8,
                padding: 8,
                marginTop: 6,
                backgroundColor: selected ? "#eff6ff" : "#fff",
              }}
            >
              <Text style={{ fontWeight: "700", color: "#0f172a" }}>{symbol || "-"}</Text>
              <Text style={{ fontSize: 12, color: "#64748b" }}>{item.name_en ?? item.name_kr ?? "—"}</Text>
            </TouchableOpacity>
          );
        })}

        <Text style={{ marginTop: 16, fontWeight: "bold" }}>포지션 (market=us)</Text>
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

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>선택 종목 진단</Text>
        <Text style={{ marginTop: 4, color: "#334155", lineHeight: 18 }}>{selectedSymbolDiag}</Text>

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
