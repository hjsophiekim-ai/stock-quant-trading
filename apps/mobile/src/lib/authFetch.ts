import { clearPersistedAuth, refreshTokens, savePersistedAuth } from "./session";
import { clearAuth, getAuthState, setAuth } from "../store/authStore";
import { jwtExpiresInSec } from "./jwt";

type EnsureTokenResult =
  | { ok: true; accessToken: string }
  | { ok: false; reason: "no_session" | "refresh_failed" };

let refreshInFlight: Promise<EnsureTokenResult> | null = null;

async function ensureFreshAccessToken(baseUrl: string, opts?: { minTtlSec?: number }): Promise<EnsureTokenResult> {
  const minTtl = typeof opts?.minTtlSec === "number" ? opts.minTtlSec : 120;
  const st = getAuthState();
  const access = st.accessToken || "";
  const refresh = st.refreshToken || "";
  const email = st.email || "";

  if (!access) return { ok: false, reason: "no_session" };
  const ttl = jwtExpiresInSec(access);
  if (ttl != null && ttl > minTtl) return { ok: true, accessToken: access };
  if (!refresh) return { ok: false, reason: "no_session" };

  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    const pair = await refreshTokens(baseUrl, refresh);
    if (!pair || !pair.access_token) {
      return { ok: false, reason: "refresh_failed" } as EnsureTokenResult;
    }
    setAuth({
      accessToken: pair.access_token,
      refreshToken: pair.refresh_token,
      email,
    });
    await savePersistedAuth({
      accessToken: pair.access_token,
      refreshToken: pair.refresh_token,
      email,
      remember: true,
    });
    return { ok: true, accessToken: pair.access_token } as EnsureTokenResult;
  })().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function clearSessionWithMessage(onSessionExpired?: (msg: string) => void) {
  await clearPersistedAuth();
  clearAuth();
  if (onSessionExpired) onSessionExpired("세션이 만료되었습니다. 다시 로그인해 주세요.");
}

export async function authFetch(
  baseUrl: string,
  input: string,
  init?: RequestInit,
  opts?: { minTtlSec?: number; onSessionExpired?: (msg: string) => void },
): Promise<Response> {
  const base = String(baseUrl || "").replace(/\/$/, "");
  const url = input.startsWith("http://") || input.startsWith("https://") ? input : base + input;

  const ensured = await ensureFreshAccessToken(base, { minTtlSec: opts?.minTtlSec });
  if (!ensured.ok) {
    await clearSessionWithMessage(opts?.onSessionExpired);
    throw new Error("SESSION_EXPIRED");
  }

  const headers = new Headers(init?.headers || {});
  headers.set("Authorization", `Bearer ${ensured.accessToken}`);
  const first = await fetch(url, { ...(init || {}), headers });
  if (first.status !== 401) return first;

  const ensured2 = await ensureFreshAccessToken(base, { minTtlSec: 0 });
  if (!ensured2.ok) {
    await clearSessionWithMessage(opts?.onSessionExpired);
    return first;
  }
  const headers2 = new Headers(init?.headers || {});
  headers2.set("Authorization", `Bearer ${ensured2.accessToken}`);
  return fetch(url, { ...(init || {}), headers: headers2 });
}

export async function ensureAuthOnForeground(
  baseUrl: string,
  opts?: { minTtlSec?: number; onSessionExpired?: (msg: string) => void },
): Promise<void> {
  const base = String(baseUrl || "").replace(/\/$/, "");
  const ensured = await ensureFreshAccessToken(base, { minTtlSec: opts?.minTtlSec ?? 300 });
  if (!ensured.ok) {
    await clearSessionWithMessage(opts?.onSessionExpired);
  }
}

