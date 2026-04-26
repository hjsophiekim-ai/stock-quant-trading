import React, { useCallback, useEffect, useState } from "react";
import { Picker } from "@react-native-picker/picker";
import { Button, SafeAreaView, ScrollView, Switch, Text, TextInput, View } from "react-native";

import { authFetch } from "../lib/authFetch";
import { DOMESTIC_STRATEGY_OPTIONS, type DomesticStrategyId, type MarketId } from "../types/trading";

type Props = {
  backendUrl: string;
};

type SafetyStatus = {
  trading_mode: "paper" | "live";
  execution_mode?: "paper_auto" | "live_shadow" | "live_manual_approval";
  live_trading_flag: boolean;
  secondary_confirm_flag: boolean;
  extra_approval_flag: boolean;
  live_emergency_stop?: boolean;
  can_place_live_order: boolean;
  trading_badge: "test" | "live";
  warning_message: string;
};

type SellOnlyArmState = {
  user_id: string;
  enabled: boolean;
  scope: string;
  armed_for_kst_date: string;
  updated_at_utc?: string;
};

type LiquidationPlan = {
  plan_id: string;
  status: "prepared" | "executed" | "canceled";
  scope: string;
  use_market_order: boolean;
  created_at_utc: string;
  items: Array<{ symbol: string; quantity: number; est_price?: number | null }>;
};

type LiveExecSession = {
  session_id: string;
  status: "running" | "stopped";
  strategy_id: DomesticStrategyId;
  market: MarketId;
  execution_mode: "live_shadow" | "live_manual_approval";
  started_at_utc: string;
  last_tick_at_utc?: string | null;
  last_error?: string | null;
};

type LiveExecStatus = {
  ok: boolean;
  session: LiveExecSession | null;
  session_running: boolean;
  supported_strategies: string[];
  blocked?: { start_blockers?: string[]; submit_blockers?: string[] };
  counts?: { final_betting_candidates?: number; final_betting_pending_approvals?: number };
};

type LiveCandidateItem = {
  candidate_id: string;
  status: string;
  symbol: string;
  side: "buy" | "sell";
  strategy_id: string;
  score?: number | null;
  quantity?: number | null;
  price?: number | null;
  stop_loss_pct?: number | null;
  rationale?: string | null;
};

const SAFE_LIVE_STRATEGIES: Array<DomesticStrategyId> = [
  "final_betting_v1",
  "scalp_rsi_flag_hf_v1",
  "scalp_macd_rsi_3m_v1",
  "swing_relaxed_v2",
];

export default function LiveTradingSettingsScreen({ backendUrl }: Props) {
  const [status, setStatus] = useState<SafetyStatus>({
    trading_mode: "paper",
    live_trading_flag: false,
    secondary_confirm_flag: false,
    extra_approval_flag: false,
    can_place_live_order: false,
    trading_badge: "test",
    warning_message: "LIVE 잠금 상태",
  });
  const [reason, setReason] = useState("운영자 수동 승인");
  const [killMessage, setKillMessage] = useState("");
  const [runtimeManualOverride, setRuntimeManualOverride] = useState(false);
  const [history, setHistory] = useState<Array<{ ts: string; actor: string; reason: string }>>([]);
  const [msg, setMsg] = useState("");
  const [sellOnlyEnabled, setSellOnlyEnabled] = useState(false);
  const [sellOnlyDate, setSellOnlyDate] = useState("");
  const [sellOnlyState, setSellOnlyState] = useState<SellOnlyArmState | null>(null);
  const [liqUseMarket, setLiqUseMarket] = useState(true);
  const [latestPlan, setLatestPlan] = useState<LiquidationPlan | null>(null);
  const [liqConfirm, setLiqConfirm] = useState("LIQUIDATE_ALL");
  const [liveStrategyId, setLiveStrategyId] = useState<DomesticStrategyId>("final_betting_v1");
  const [liveMarket, setLiveMarket] = useState<MarketId>("domestic");
  const [liveExecMode, setLiveExecMode] = useState<"live_shadow" | "live_manual_approval">("live_shadow");
  const [liveExecStatus, setLiveExecStatus] = useState<LiveExecStatus | null>(null);
  const [finalBettingCandidates, setFinalBettingCandidates] = useState<LiveCandidateItem[]>([]);

  const refresh = async () => {
    const statusRes = await authFetch(backendUrl, `/api/live-trading/status`);
    const statusData = await statusRes.json();
    if (statusRes.ok) setStatus(statusData);

    const killRes = await authFetch(backendUrl, `/api/live-trading/kill-switch-status`);
    const killData = await killRes.json();
    if (killRes.ok) {
      setKillMessage(
        killData.loss_limit_exceeded
          ? `손실 제한 초과 경고: daily=${killData.daily_loss_pct}% total=${killData.total_loss_pct}%`
          : "손실 제한 정상 범위",
      );
    }

    const rtRes = await authFetch(backendUrl, `/api/runtime-engine/status`);
    const rtData = await rtRes.json();
    if (rtRes.ok) {
      setRuntimeManualOverride(Boolean(rtData.manual_override_enabled));
    }

    const histRes = await authFetch(backendUrl, `/api/live-trading/settings-history`);
    const histData = await histRes.json();
    if (histRes.ok) setHistory(histData.items ?? []);

    const armRes = await authFetch(backendUrl, `/api/live-prep/sell-only-arm/status`);
    const armData = await armRes.json();
    if (armRes.ok) {
      const st = armData?.state ?? null;
      setSellOnlyState(st);
      setSellOnlyEnabled(Boolean(st?.enabled));
      setSellOnlyDate(String(st?.armed_for_kst_date ?? ""));
    }

    const planRes = await authFetch(backendUrl, `/api/live-prep/batch-liquidation/plans?limit=1`);
    const planData = await planRes.json();
    if (planRes.ok) {
      const p0 = Array.isArray(planData?.plans) && planData.plans.length ? planData.plans[0] : null;
      setLatestPlan(p0);
    }

    const execRes = await authFetch(backendUrl, `/api/live-exec/status`);
    const execData = await execRes.json();
    if (execRes.ok) {
      setLiveExecStatus(execData);
      const sess = execData?.session ?? null;
      if (sess?.strategy_id) setLiveStrategyId(sess.strategy_id);
      if (sess?.market) setLiveMarket(sess.market);
      if (sess?.execution_mode) setLiveExecMode(sess.execution_mode);
    }

    const candRes = await authFetch(backendUrl, `/api/live-prep/candidates?strategy_id=final_betting_v1&limit=20`);
    const candData = await candRes.json();
    if (candRes.ok) {
      setFinalBettingCandidates(Array.isArray(candData?.items) ? candData.items : []);
    }
  };

  useEffect(() => {
    void refresh();
  }, [backendUrl]);

  const save = async () => {
    const res = await authFetch(backendUrl, `/api/live-trading/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        live_trading_flag: status.live_trading_flag,
        secondary_confirm_flag: status.secondary_confirm_flag,
        extra_approval_flag: status.extra_approval_flag,
        reason,
        actor: "mobile-user",
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMsg(data?.detail ?? "저장 실패");
      return;
    }
    setStatus(data);
    setMsg(data.warning_message ?? "저장 완료");
    await refresh();
  };

  const toggleRuntimeManualOverride = async () => {
    const res = await authFetch(backendUrl, `/api/runtime-engine/manual-override-toggle`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      setMsg(typeof data?.detail === "string" ? data.detail : "runtime 수동 재개 토글 실패");
      return;
    }
    setRuntimeManualOverride(Boolean(data.manual_override_enabled));
    setMsg(Boolean(data.manual_override_enabled) ? "runtime 수동 재개 ON" : "runtime 수동 재개 OFF");
    await refresh();
  };

  const saveSellOnlyArm = async () => {
    const res = await authFetch(backendUrl, `/api/live-prep/sell-only-arm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: sellOnlyEnabled,
        armed_for_kst_date: sellOnlyDate,
        actor: "mobile-user",
        reason: reason || "arm",
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMsg(typeof data?.detail === "string" ? data.detail : "Sell-only arm 저장 실패");
      return;
    }
    setSellOnlyState(data?.state ?? null);
    setMsg("Sell-only arm 저장 완료");
    await refresh();
  };

  const prepareLiquidation = async () => {
    const res = await authFetch(backendUrl, `/api/live-prep/batch-liquidation/prepare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        use_market_order: liqUseMarket,
        actor: "mobile-user",
        reason: reason || "prepare",
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMsg(typeof data?.detail === "string" ? data.detail : "전체 청산 준비 실패");
      return;
    }
    setLatestPlan(data?.plan ?? null);
    setMsg("전체 청산 플랜 준비 완료");
    await refresh();
  };

  const executeLiquidation = async () => {
    if (!latestPlan?.plan_id) {
      setMsg("실행할 준비된 플랜이 없습니다.");
      return;
    }
    const res = await authFetch(backendUrl, `/api/live-prep/batch-liquidation/${latestPlan.plan_id}/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        confirm: liqConfirm,
        actor: "mobile-user",
        reason: reason || "execute",
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMsg(typeof data?.detail === "string" ? data.detail : "전체 청산 실행 실패");
      return;
    }
    setMsg(`전체 청산 실행 완료 (submitted=${Array.isArray(data?.submitted) ? data.submitted.length : 0})`);
    await refresh();
  };

  const startLive = async () => {
    const res = await authFetch(backendUrl, `/api/live-exec/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        strategy_id: liveStrategyId,
        market: liveMarket,
        execution_mode: liveExecMode,
        actor: "mobile-user",
        reason: reason || "start",
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMsg(typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? data));
      return;
    }
    setMsg("Live session started");
    await refresh();
  };

  const stopLive = async () => {
    const res = await authFetch(backendUrl, `/api/live-exec/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actor: "mobile-user",
        reason: reason || "stop",
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMsg(typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? data));
      return;
    }
    setMsg("Live session stopped");
    await refresh();
  };

  const tickLive = async () => {
    const res = await authFetch(backendUrl, `/api/live-exec/tick`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      setMsg(typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? data));
      return;
    }
    const c = data?.counts ? JSON.stringify(data.counts) : "";
    setMsg(`Tick OK ${c}`);
    await refresh();
  };

  const approveCandidate = async (candidateId: string) => {
    const res = await authFetch(backendUrl, `/api/live-prep/candidates/${candidateId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor: "mobile-user", reason: reason || "approve" }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMsg(typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? data));
      return;
    }
    setMsg("Approved");
    await refresh();
  };

  const rejectCandidate = async (candidateId: string) => {
    const res = await authFetch(backendUrl, `/api/live-prep/candidates/${candidateId}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor: "mobile-user", reason: reason || "reject" }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMsg(typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? data));
      return;
    }
    setMsg("Rejected");
    await refresh();
  };

  const submitCandidate = async (candidateId: string) => {
    const res = await authFetch(backendUrl, `/api/live-prep/candidates/${candidateId}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor: "mobile-user", reason: reason || "submit" }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMsg(typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? data));
      return;
    }
    setMsg("Submitted");
    await refresh();
  };

  return (
    <SafeAreaView>
      <ScrollView style={{ padding: 12 }}>
        <Text style={{ fontSize: 20, fontWeight: "bold" }}>Live Trading</Text>
        <Text style={{ color: "#b91c1c", marginTop: 6 }}>
          경고: 실거래는 고위험입니다. 명시적 다중 승인 없이는 잠금 해제되지 않습니다.
        </Text>

        <Text style={{ marginTop: 14, fontWeight: "bold" }}>실행 콘솔</Text>
        <Text style={{ color: "#334155" }}>
          Paper처럼 전략을 선택하고 Start/Stop/Tick으로 운영합니다. 자동 주문 실행 모드는 제공하지 않습니다.
        </Text>
        <Text style={{ marginTop: 8 }}>Session running: {liveExecStatus?.session_running ? "YES" : "NO"}</Text>
        <Text>
          Pending approvals: {String(liveExecStatus?.counts?.final_betting_pending_approvals ?? 0)} / Candidates:{" "}
          {String(liveExecStatus?.counts?.final_betting_candidates ?? 0)}
        </Text>
        <Text style={{ marginTop: 8, fontWeight: "bold" }}>Strategy</Text>
        <Picker selectedValue={liveStrategyId} onValueChange={(v) => setLiveStrategyId(v as DomesticStrategyId)}>
          {DOMESTIC_STRATEGY_OPTIONS.filter((o) => SAFE_LIVE_STRATEGIES.includes(o.id as DomesticStrategyId)).map((o) => (
            <Picker.Item key={o.id} label={o.label} value={o.id} />
          ))}
        </Picker>

        <Text style={{ marginTop: 8, fontWeight: "bold" }}>Execution Mode</Text>
        <Picker selectedValue={liveExecMode} onValueChange={(v) => setLiveExecMode(v as any)}>
          <Picker.Item label="live_shadow" value="live_shadow" />
          <Picker.Item label="live_manual_approval" value="live_manual_approval" />
        </Picker>

        <Text style={{ marginTop: 8, fontWeight: "bold" }}>Market</Text>
        <Picker selectedValue={liveMarket} onValueChange={(v) => setLiveMarket(v as MarketId)}>
          <Picker.Item label="domestic" value="domestic" />
        </Picker>

        <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
          <Button title="Start" onPress={startLive} />
          <Button title="Stop" onPress={stopLive} />
          <Button title="Tick" onPress={tickLive} />
        </View>
        {Array.isArray(liveExecStatus?.blocked?.start_blockers) && liveExecStatus?.blocked?.start_blockers?.length ? (
          <Text style={{ marginTop: 8, color: "#b91c1c" }}>
            Start blocked: {"\n"}- {liveExecStatus.blocked.start_blockers.join("\n- ")}
          </Text>
        ) : null}
        {Array.isArray(liveExecStatus?.blocked?.submit_blockers) && liveExecStatus?.blocked?.submit_blockers?.length ? (
          <Text style={{ marginTop: 8, color: "#b91c1c" }}>
            Live submit blocked: {"\n"}- {liveExecStatus.blocked.submit_blockers.join("\n- ")}
          </Text>
        ) : null}

        {liveStrategyId === "final_betting_v1" ? (
          <View style={{ marginTop: 16 }}>
            <Text style={{ fontWeight: "bold" }}>final_betting 후보/승인</Text>
            <Text style={{ color: "#334155" }}>
              이 목록은 시스템이 코드 정의된 유니버스에서 계산한 후보입니다. 실주문은 수동 승인 없이는 제출되지 않습니다.
            </Text>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
              <Button title="Refresh Candidates" onPress={refresh} />
              <Button title="Tick Now" onPress={tickLive} />
            </View>
            {finalBettingCandidates.length === 0 ? (
              <Text style={{ marginTop: 8, color: "#334155" }}>후보 없음</Text>
            ) : (
              finalBettingCandidates.map((c) => (
                <View
                  key={c.candidate_id}
                  style={{ borderWidth: 1, borderColor: "#cbd5e1", padding: 10, borderRadius: 8, marginTop: 8 }}
                >
                  <Text style={{ fontWeight: "bold" }}>
                    {c.status} · {c.symbol} · {c.side}
                  </Text>
                  <Text style={{ color: "#334155" }}>
                    qty={String(c.quantity ?? "-")} price={String(c.price ?? "-")} score={String(c.score ?? "-")} sl%=
                    {String(c.stop_loss_pct ?? "-")}
                  </Text>
                  <Text style={{ color: "#334155" }}>{c.rationale ?? ""}</Text>
                  <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
                    <Button title="Approve" onPress={() => approveCandidate(c.candidate_id)} />
                    <Button title="Reject" onPress={() => rejectCandidate(c.candidate_id)} />
                    <Button title="Submit" onPress={() => submitCandidate(c.candidate_id)} />
                  </View>
                </View>
              ))
            )}
          </View>
        ) : null}

        <Text style={{ marginTop: 16, fontWeight: "bold" }}>안전/잠금 상태</Text>
        <Text style={{ marginTop: 8 }}>Badge: {status.trading_badge.toUpperCase()}</Text>
        <Text>Mode: {status.trading_mode}</Text>
        <Text>Execution: {status.execution_mode ?? "-"}</Text>
        <Text>Can Place Live Order: {status.can_place_live_order ? "YES" : "NO"}</Text>
        <Text style={{ marginBottom: 8 }}>{status.warning_message}</Text>
        <Text>Emergency Stop: {status.live_emergency_stop ? "ON" : "OFF"}</Text>

        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <Text>1) Live Enable Flag</Text>
          <Switch value={status.live_trading_flag} onValueChange={(v) => setStatus({ ...status, live_trading_flag: v })} />
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <Text>2) Secondary Confirmation</Text>
          <Switch
            value={status.secondary_confirm_flag}
            onValueChange={(v) => setStatus({ ...status, secondary_confirm_flag: v })}
          />
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <Text>3) Extra Approval</Text>
          <Switch value={status.extra_approval_flag} onValueChange={(v) => setStatus({ ...status, extra_approval_flag: v })} />
        </View>
        <TextInput value={reason} onChangeText={setReason} placeholder="변경 사유" style={{ borderWidth: 1, padding: 8, marginTop: 8 }} />
        <Button title="Save Safety Settings" onPress={save} />
        <View style={{ height: 8 }} />
        <Button title="Refresh Status" onPress={refresh} />
        <Text style={{ marginTop: 8 }}>{msg}</Text>
        <Text style={{ marginTop: 8, color: "#b91c1c" }}>{killMessage}</Text>
        <Text style={{ marginTop: 8, color: runtimeManualOverride ? "#b91c1c" : "#334155" }}>
          Runtime 수동 재개 토글: {runtimeManualOverride ? "ON" : "OFF"}
        </Text>
        <Button
          title={runtimeManualOverride ? "Runtime 수동 재개 토글 OFF" : "Runtime 수동 재개 토글 ON"}
          onPress={toggleRuntimeManualOverride}
        />

        <Text style={{ marginTop: 16, fontWeight: "bold" }}>Sell-Only Arm (final_betting 전용)</Text>
        <Text style={{ color: "#334155" }}>
          무장한 날짜 오전 윈도우에서 final_betting 포지션의 매도 신호만 자동 제출됩니다.
        </Text>
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 8 }}>
          <Text>Enable</Text>
          <Switch value={sellOnlyEnabled} onValueChange={setSellOnlyEnabled} />
        </View>
        <TextInput
          value={sellOnlyDate}
          onChangeText={setSellOnlyDate}
          placeholder="YYYYMMDD (기본: 내일)"
          style={{ borderWidth: 1, padding: 8, marginTop: 8 }}
        />
        <Button title="Save Sell-Only Arm" onPress={saveSellOnlyArm} />
        <Text style={{ marginTop: 8, color: "#334155" }}>{sellOnlyState ? JSON.stringify(sellOnlyState) : "-"}</Text>

        <Text style={{ marginTop: 16, fontWeight: "bold" }}>전체 청산(1클릭) 준비/실행</Text>
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 8 }}>
          <Text>Market(가격 0)</Text>
          <Switch value={liqUseMarket} onValueChange={setLiqUseMarket} />
        </View>
        <Button title="Prepare Liquidation Plan" onPress={prepareLiquidation} />
        <Text style={{ marginTop: 8 }}>Latest Plan: {latestPlan?.plan_id ?? "-"}</Text>
        <TextInput
          value={liqConfirm}
          onChangeText={setLiqConfirm}
          placeholder="LIQUIDATE_ALL"
          style={{ borderWidth: 1, padding: 8, marginTop: 8 }}
        />
        <Button title="Execute Latest Plan" onPress={executeLiquidation} />

        <Text style={{ marginTop: 12, fontWeight: "bold" }}>Settings Change History</Text>
        {history.slice(0, 10).map((h, idx) => (
          <Text key={`${h.ts}-${idx}`}>
            {h.ts} / {h.actor} / {h.reason}
          </Text>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}
