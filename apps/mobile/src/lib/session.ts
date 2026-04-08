import AsyncStorage from "@react-native-async-storage/async-storage";

const AUTH_KEY = "@sq/auth_session_v1";
const ONBOARDING_KEY = "@sq/onboarding_done_v1";

export type PersistedAuth = {
  accessToken: string;
  refreshToken: string;
  email: string;
  remember: boolean;
};

export async function getOnboardingDone(): Promise<boolean> {
  const v = await AsyncStorage.getItem(ONBOARDING_KEY);
  return v === "true";
}

export async function setOnboardingDone(): Promise<void> {
  await AsyncStorage.setItem(ONBOARDING_KEY, "true");
}

export async function loadPersistedAuth(): Promise<PersistedAuth | null> {
  const raw = await AsyncStorage.getItem(AUTH_KEY);
  if (!raw) return null;
  try {
    const j = JSON.parse(raw) as PersistedAuth;
    if (!j.accessToken || j.remember === false) return null;
    return j;
  } catch {
    return null;
  }
}

export async function savePersistedAuth(session: PersistedAuth): Promise<void> {
  await AsyncStorage.setItem(AUTH_KEY, JSON.stringify(session));
}

export async function clearPersistedAuth(): Promise<void> {
  await AsyncStorage.removeItem(AUTH_KEY);
}

export async function validateAccessToken(
  baseUrl: string,
  accessToken: string,
): Promise<boolean> {
  try {
    const r = await fetch(`${baseUrl}/api/auth/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return r.ok;
  } catch {
    return false;
  }
}

export async function refreshTokens(
  baseUrl: string,
  refreshToken: string,
): Promise<{ access_token: string; refresh_token: string } | null> {
  try {
    const r = await fetch(`${baseUrl}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}
