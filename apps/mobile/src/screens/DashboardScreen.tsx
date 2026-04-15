import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Button,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import { clearPersistedAuth } from "../lib/session";
import { clearAuth, getAuthState } from "../store/authStore";
import { type MarketStatusCard } from "../types/trading";

const POLL_MS = 12_000;

type Props = {
  backendUrl: string;
  onOpenBrokerSettings: () => void;
};

type TabKey = "overview" | "positions" | "orders" | "logs";

function num(v: unknown, fb = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fb;
}

function EmptyHint({ text }: { text: string }) {
  return (
    <View style={{ paddingVertical: 16, alignItems: "center" }}>
      <Text style={{ color: "#64748b", fontSize: 13, textAlign: "center" }}>{text}</Text>
    </View>
  );
}

export default function DashboardScreen({ backendUrl, onOpenBrokerSettings }: Props) {
  const state = getAuthState();
  const [tab, setTab] = useState<TabKey>("overview");
  const [summary, setSummary] = useState<any>(null);
  const [recentTrades, setRecentTrades] = useState<any[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [brokerLinked, setBrokerLinked] = useState<boolean | null>(null);
  const [initialLoad, setInitialLoad] = useState(true);
  const mounted = useRef(true);

  const authHeaders = useCallback((): HeadersInit => {
    const token = getAuthState().accessToken;
    const h: Record<string, string> = {};
    if (token) h.Authorization = `Bearer ${token}`;
    return h;
  }, []);

  const load = useCallback(
    async (opts?: { isPull?: boolean }) => {
      if (!mounted.current) return;
      const pull = opts?.isPull;
      if (pull) setRefreshing(true);
      else setLoading(true);
      try {
        const headers = authHeaders();
        const brokerRes = await fetch(`${backendUrl}/api/broker-accounts/me`, { headers });
        if (brokerRes.status === 404) setBrokerLinked(false);
        else if (brokerRes.ok) setBrokerLinked(true);
        else setBrokerLinked(null);

        const [summaryRes, tradesRes] = await Promise.all([
          fetch(`${backendUrl}/api/dashboard/summary`, { headers }),
          fetch(`${backendUrl}/api/trading/recent-trades?limit=15`, { headers }),
        ]);
        const summaryData = await summaryRes.json();
        const tradesData = await tradesRes.json();
        if (!summaryRes.ok) {
          setMessage(typeof summaryData?.detail === "string" ? summaryData.detail : "대시보드를 불러오지 못했습니다.");
          setSummary(null);
          return;
        }
        setMessage("");
        setSummary(summaryData);
        setRecentTrades(tradesData?.items ?? []);
      } catch {
        setMessage("네트워크 오류 — 서버 주소와 연결을 확인하세요.");
        setSummary(null);
      } finally {
        if (mounted.current) {
          setLoading(false);
          setRefreshing(false);
          setInitialLoad(false);
        }
      }
    },
    [authHeaders, backendUrl],
  );

  const onLogout = async () => {
    const refresh = getAuthState().refreshToken;
    if (refresh) {
      try {
        await fetch(`${backendUrl}/api/auth/logout`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
      } catch {
        /* still clear */
      }
    }
    await clearPersistedAuth();
    clearAuth();
  };

  useEffect(() => {
    mounted.current = true;
    void load();
    const id = setInterval(() => void load(), POLL_MS);
    return () => {
      mounted.current = false;
      clearInterval(id);
    };
  }, [load]);

  const cardStyle = {
    backgroundColor: "#ffffff",
    borderRadius: 10,
    padding: 12,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: "#e2e8f0",
  } as const;

  const riskBg =
    summary?.risk_banner?.level === "critical"
      ? "#fee2e2"
      : summary?.risk_banner?.level === "warning"
        ? "#fff7ed"
        : "#ecfdf5";

  const broker = summary?.broker ?? {};
  const ub = summary?.user_broker_account;
  const rt = summary?.runtime_engine ?? {};
  const alerts = summary?.alerts ?? {};
  const regime = summary?.market_regime ?? {};
  const strat = summary?.strategy_signals ?? {};
  const paperDemo = summary?.paper_trading_demo ?? {};
  const todos: string[] = summary?.dashboard_todos ?? [];
  const candidates = (summary?.selected_candidates ?? summary?.screener?.candidates ?? []) as any[];
  const marketCardsFromApi = (summary?.market_status_cards ?? []) as MarketStatusCard[];
  const fallbackMarketCards: MarketStatusCard[] = [
    {
      market: "domestic",
      title: "Domestic",
      status: summary?.paper_trading?.status ?? summary?.paper_trading_demo?.status ?? "unknown",
      session_state: summary?.paper_trading?.krx_session_state ?? summary?.runtime_engine?.market_phase_now ?? "closed",
      message: summary?.paper_trading?.strategy_id
        ? `strategy=${summary.paper_trading.strategy_id}`
        : "세션 정보 없음",
    },
    {
      market: "us",
      title: "US",
      status: "unknown",
      session_state: "closed",
      message: "US 상태 카드를 아직 제공하지 않으면 US 화면에서 직접 확인하세요.",
    },
  ];
  const marketCards = marketCardsFromApi.length > 0 ? marketCardsFromApi : fallbackMarketCards;

  const tabBtn = (k: TabKey, label: string) => (
    <Pressable
      key={k}
      onPress={() => setTab(k)}
      style={{
        paddingVertical: 8,
        paddingHorizontal: 10,
        borderRadius: 8,
        backgroundColor: tab === k ? "#2563eb" : "#f1f5f9",
        marginRight: 6,
      }}
    >
      <Text style={{ fontWeight: "700", fontSize: 12, color: tab === k ? "#fff" : "#334155" }}>{label}</Text>
    </Pressable>
  );

  const positions = (summary?.positions ?? []) as any[];
  const openOrders = (summary?.open_orders ?? []) as any[];
  const recentFills = (summary?.recent_fills ?? []) as any[];
  const logs = (summary?.recent_logs ?? []) as any[];

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#f8fafc" }}>
      <View style={{ paddingHorizontal: 12, paddingTop: 8, paddingBottom: 4 }}>
        <Text style={{ fontSize: 20, fontWeight: "800" }}>운영 대시보드</Text>
        <Text style={{ color: "#64748b", fontSize: 11, marginTop: 2 }}>
          {summary?.updated_at_utc ? `갱신(UTC): ${summary.updated_at_utc}` : initialLoad ? "" : "—"}
          {loading && !refreshing ? " · 로딩…" : ` · ${POLL_MS / 1000}s 폴링`}
        </Text>
        <Text style={{ fontSize: 12, color: "#334155", marginTop: 4 }}>User: {state.email ?? "-"}</Text>
      </View>

      <ScrollView
        style={{ flex: 1, paddingHorizontal: 12 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => void load({ isPull: true })} tintColor="#2563eb" />
        }
      >
        <View style={{ flexDirection: "row", flexWrap: "wrap", marginBottom: 10 }}>{tabBtn("overview", "개요")}{tabBtn("positions", "포지션")}{tabBtn("orders", "주문·체결")}{tabBtn("logs", "로그")}</View>

        {message ? (
          <View style={{ ...cardStyle, backgroundColor: "#fef2f2", borderColor: "#fecaca" }}>
            <Text style={{ color: "#991b1b", fontWeight: "600" }}>{message}</Text>
          </View>
        ) : null}

        {brokerLinked === false ? (
          <View
            style={{
              backgroundColor: "#fff7ed",
              borderColor: "#fdba74",
              borderWidth: 1,
              borderRadius: 10,
              padding: 12,
              marginBottom: 10,
            }}
          >
            <Text style={{ fontWeight: "700", marginBottom: 4 }}>브로커 계정이 아직 없습니다</Text>
            <Text style={{ fontSize: 13, color: "#9a3412", marginBottom: 8 }}>
              앱에 등록한 한국투자 연동이 없으면 리스크 배너·Paper 시작 조건에 반영되지 않습니다.
            </Text>
            <TouchableOpacity onPress={onOpenBrokerSettings}>
              <Text style={{ color: "#c2410c", fontWeight: "600" }}>브로커 설정 열기 →</Text>
            </TouchableOpacity>
          </View>
        ) : null}

        {initialLoad && !summary ? (
          <View style={{ padding: 24, alignItems: "center" }}>
            <ActivityIndicator size="large" />
            <Text style={{ marginTop: 8, color: "#64748b" }}>대시보드 불러오는 중…</Text>
          </View>
        ) : null}

        {!initialLoad && !summary ? <EmptyHint text="데이터가 없습니다. 아래 새로고침을 눌러 다시 시도하세요." /> : null}

        {summary && tab === "overview" ? (
          <>
            <View style={{ ...cardStyle, backgroundColor: riskBg, borderColor: "#cbd5e1" }}>
              <Text style={{ fontWeight: "800" }}>[{summary.risk_banner?.level}] 운영 리스크</Text>
              <Text style={{ marginTop: 4 }}>{summary.risk_banner?.message}</Text>
              {(alerts.portfolio_sync_risk_review || alerts.runtime_risk_off) && (
                <Text style={{ marginTop: 8, color: "#b91c1c", fontWeight: "600" }}>
                  {alerts.portfolio_sync_risk_review ? "· 포트폴리오 sync 검토 플래그" : ""}
                  {alerts.runtime_risk_off ? " · 런타임 RISK_OFF" : ""}
                </Text>
              )}
            </View>

            <View style={cardStyle}>
              <Text style={{ fontWeight: "800", marginBottom: 6 }}>모드 · 손익</Text>
              <Text>
                현재 모드: <Text style={{ fontWeight: "700" }}>{summary.mode}</Text>
                {summary.live_execution_armed ? " (live 실행 잠금 해제됨)" : ""}
              </Text>
              <Text style={{ marginTop: 6 }}>오늘 {num(summary.today_return_pct).toFixed(2)}% · 당월 {num(summary.monthly_return_pct).toFixed(2)}% · 누적 {num(summary.cumulative_return_pct).toFixed(2)}%</Text>
              <Text style={{ marginTop: 4 }}>
                실현 / 미실현: {num(summary.realized_pnl).toLocaleString()} / {num(summary.unrealized_pnl).toLocaleString()} 원(스냅샷 기준)
              </Text>
              <Text style={{ fontSize: 11, color: "#64748b", marginTop: 6 }}>
                포트폴리오: {summary.portfolio?.synced ? "동기화됨" : "스냅샷 없음 — POST /api/portfolio/sync"}{" "}
                {summary.portfolio?.updated_at_utc ? `(${summary.portfolio.updated_at_utc})` : ""}
              </Text>
            </View>

            <View style={cardStyle}>
              <Text style={{ fontWeight: "800", marginBottom: 6 }}>시장 상태 (Domestic / US)</Text>
              {marketCards.map((card, idx) => (
                <View
                  key={`${card.market ?? "market"}-${idx}`}
                  style={{
                    backgroundColor: "#f8fafc",
                    borderColor: "#e2e8f0",
                    borderWidth: 1,
                    borderRadius: 8,
                    padding: 8,
                    marginBottom: 6,
                  }}
                >
                  <Text style={{ fontWeight: "700" }}>{card.title ?? String(card.market ?? "market").toUpperCase()}</Text>
                  <Text style={{ fontSize: 12, marginTop: 2 }}>
                    status: {card.status ?? "unknown"} · session: {card.session_state ?? "closed"}
                  </Text>
                  {card.message ? <Text style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>{card.message}</Text> : null}
                </View>
              ))}
            </View>

            <View style={cardStyle}>
              <Text style={{ fontWeight: "800", marginBottom: 4 }}>브로커</Text>
              <Text style={{ fontSize: 12, color: "#64748b", marginBottom: 4 }}>서버 런타임 (.env KIS)</Text>
              <Text>
                {broker.token_ok ? "토큰 OK" : "토큰 실패"} — {broker.message ?? ""}
              </Text>
              <Text style={{ fontSize: 11, color: "#64748b" }}>{broker.kis_api_base ?? ""}</Text>
              <Text style={{ fontSize: 12, color: "#64748b", marginTop: 8, marginBottom: 4 }}>앱 등록 계정</Text>
              {ub ? (
                <Text>
                  {ub.connection_status === "success" ? "연결됨" : "미연결"} — {ub.connection_message ?? ""}
                  {"\n"}
                  {ub.kis_account_no_masked ?? ""} · mode {ub.trading_mode}
                </Text>
              ) : (
                <Text style={{ color: "#64748b" }}>미등록</Text>
              )}
            </View>

            <View style={cardStyle}>
              <Text style={{ fontWeight: "800", marginBottom: 4 }}>런타임 · 하트비트</Text>
              <Text>
                시스템: {summary.system_status} · 엔진 {rt.engine_state} · 스레드 {rt.loop_thread_alive ? "alive" : "stopped"}
              </Text>
              <Text style={{ marginTop: 4 }}>
                장세 {rt.market_phase_now ?? "-"} · 실패 {num(rt.failure_streak)}/{num(rt.max_failures)}
              </Text>
              <Text style={{ marginTop: 4 }}>마지막 하트비트: {summary.last_heartbeat_utc ?? "-"}</Text>
              {rt.last_error ? <Text style={{ color: "#b45309", marginTop: 4 }}>{rt.last_error}</Text> : null}
            </View>

            <View style={cardStyle}>
              <Text style={{ fontWeight: "800", marginBottom: 4 }}>시장 국면 · 후보</Text>
              <Text>
                스크리너: {regime.screener_regime ?? "-"} {regime.screener_blocked ? "(차단)" : ""}
              </Text>
              <Text>신호 엔진 국면: {regime.signal_engine_regime ?? "-"}</Text>
              {strat.status === "empty" ? (
                <Text style={{ marginTop: 6, color: "#64748b" }}>{strat.message}</Text>
              ) : (
                <Text style={{ marginTop: 6 }}>
                  대기 신호 {num(strat.pending_signals_count)} · 진단 종목 {num(strat.symbols_diagnosed)} · {strat.evaluated_at_utc ?? ""}
                </Text>
              )}
              <Text style={{ fontWeight: "700", marginTop: 10, marginBottom: 4 }}>선정 후보 심볼</Text>
              {candidates.length === 0 ? (
                <Text style={{ color: "#64748b" }}>후보 없음 또는 스크리너 미실행</Text>
              ) : (
                candidates.slice(0, 10).map((c: any) => (
                  <Text key={c.symbol}>
                    {c.symbol} · score {c.total_score} · {(c.reasons?.[0] as string) ?? ""}
                  </Text>
                ))
              )}
            </View>

            <View style={cardStyle}>
              <Text style={{ fontWeight: "800", marginBottom: 4 }}>데모 Paper (별도 트랙)</Text>
              <Text>
                {paperDemo.status ?? "-"} · {paperDemo.strategy_id ?? "-"} · hb {paperDemo.last_heartbeat_at ?? "-"}
              </Text>
            </View>

            {todos.length > 0 ? (
              <View style={{ ...cardStyle, backgroundColor: "#fffbeb", borderColor: "#fcd34d" }}>
                <Text style={{ fontWeight: "800", marginBottom: 6 }}>데이터 한계 (TODO)</Text>
                {todos.map((t, i) => (
                  <Text key={i} style={{ fontSize: 11, color: "#78350f", marginBottom: 4 }}>
                    · {t}
                  </Text>
                ))}
              </View>
            ) : null}
          </>
        ) : null}

        {summary && tab === "positions" ? (
          <View style={cardStyle}>
            <Text style={{ fontWeight: "800", marginBottom: 8 }}>보유 포지션 ({positions.length})</Text>
            {positions.length === 0 ? (
              <EmptyHint text="포지션이 없거나 포트폴리오 동기화 전입니다." />
            ) : (
              positions.map((p: any) => (
                <View key={p.symbol} style={{ borderBottomWidth: 1, borderBottomColor: "#f1f5f9", paddingVertical: 8 }}>
                  <Text style={{ fontWeight: "700" }}>{p.symbol}</Text>
                  <Text style={{ fontSize: 13, color: "#475569" }}>
                    수량 {p.quantity} · 평단 {p.average_price_kis ?? p.average_price_internal ?? "-"} · 현재가 {p.current_price ?? "-"}
                  </Text>
                  <Text style={{ fontSize: 12, color: "#64748b" }}>평가손익 {p.unrealized_pnl_kis ?? "-"}</Text>
                </View>
              ))
            )}
          </View>
        ) : null}

        {summary && tab === "orders" ? (
          <>
            <View style={cardStyle}>
              <Text style={{ fontWeight: "800", marginBottom: 8 }}>미체결 ({openOrders.length})</Text>
              {summary.open_orders_error ? (
                <Text style={{ color: "#b45309", marginBottom: 8 }}>{summary.open_orders_error}</Text>
              ) : null}
              {openOrders.length === 0 ? (
                <EmptyHint text="미체결 주문이 없습니다." />
              ) : (
                openOrders.map((o: any) => (
                  <Text key={o.order_id} style={{ marginBottom: 6, fontSize: 13 }}>
                    {o.symbol} {String(o.side).toUpperCase()} rem {o.remaining_quantity}/{o.quantity} @{o.price ?? "MKT"}
                  </Text>
                ))
              )}
            </View>
            <View style={cardStyle}>
              <Text style={{ fontWeight: "800", marginBottom: 8 }}>최근 체결</Text>
              {summary.recent_fills_error ? (
                <Text style={{ color: "#b45309", marginBottom: 8 }}>{summary.recent_fills_error}</Text>
              ) : null}
              {recentFills.length === 0 ? (
                <EmptyHint text="fills.jsonl 에 기록된 체결이 없습니다. 동기화 후 확인하세요." />
              ) : (
                recentFills.map((f: any) => (
                  <Text key={String(f.fill_id)} style={{ marginBottom: 6, fontSize: 13 }}>
                    {f.symbol} {String(f.side).toUpperCase()} {f.quantity} @ {f.price}
                  </Text>
                ))
              )}
            </View>
            <View style={cardStyle}>
              <Text style={{ fontWeight: "800", marginBottom: 8 }}>최근 거래 API (/api/trading/recent-trades)</Text>
              {recentTrades.length === 0 ? (
                <EmptyHint text="거래 이력이 없습니다." />
              ) : (
                recentTrades.map((trade) => (
                  <Text key={trade.trade_id} style={{ marginBottom: 6, fontSize: 13 }}>
                    {trade.symbol} {String(trade.side).toUpperCase()} {trade.quantity} @ {trade.price}
                  </Text>
                ))
              )}
            </View>
          </>
        ) : null}

        {summary && tab === "logs" ? (
          <View style={cardStyle}>
            <Text style={{ fontWeight: "800", marginBottom: 8 }}>최근 로그</Text>
            {logs.length === 0 ? (
              <EmptyHint text="표시할 로그가 없습니다." />
            ) : (
              logs.map((log: any, i: number) => (
                <Text key={i} style={{ fontSize: 10, fontFamily: "monospace", marginBottom: 6, color: "#334155" }}>
                  [{log.source}] {log.message}
                </Text>
              ))
            )}
          </View>
        ) : null}

        <View style={{ height: 12 }} />
        <Button title="새로고침" onPress={() => void load()} />
        <View style={{ height: 8 }} />
        <Button title="Broker Settings" onPress={onOpenBrokerSettings} />
        <View style={{ height: 8 }} />
        <Button title="Logout" onPress={() => void onLogout()} />
        <View style={{ height: 24 }} />
      </ScrollView>
    </SafeAreaView>
  );
}
