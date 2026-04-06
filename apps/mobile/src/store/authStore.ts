export type AuthState = {
  accessToken: string | null;
  refreshToken: string | null;
  email: string | null;
};

const state: AuthState = {
  accessToken: null,
  refreshToken: null,
  email: null,
};

type Listener = (next: AuthState) => void;
const listeners = new Set<Listener>();

export function getAuthState(): AuthState {
  return { ...state };
}

export function subscribeAuth(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit(): void {
  const snapshot = getAuthState();
  listeners.forEach((l) => l(snapshot));
}

export function setAuth(next: AuthState): void {
  state.accessToken = next.accessToken;
  state.refreshToken = next.refreshToken;
  state.email = next.email;
  emit();
}

export function clearAuth(): void {
  state.accessToken = null;
  state.refreshToken = null;
  state.email = null;
  emit();
}
