/**
 * Electron(userData 파일) + sessionStorage + localStorage 에서 세션 복원.
 * 모든 보호된 HTML에서 runtime-config.js 다음에 로드하세요.
 */
async function resolveDesktopSession() {
  if (typeof window !== "undefined" && window.appBridge) {
    try {
      const t = await window.appBridge.authLoad();
      if (t && t.accessToken) {
        return {
          accessToken: t.accessToken,
          refreshToken: t.refreshToken || "",
          email: t.email || "",
        };
      }
    } catch {
      /* ignore */
    }
  }
  const accessToken =
    sessionStorage.getItem("accessToken") || localStorage.getItem("accessToken");
  if (!accessToken) {
    return null;
  }
  return {
    accessToken,
    refreshToken:
      sessionStorage.getItem("refreshToken") || localStorage.getItem("refreshToken") || "",
    email: sessionStorage.getItem("email") || localStorage.getItem("email") || "",
  };
}

function effectiveBackendUrl() {
  const def = window.RUNTIME_CONFIG?.BACKEND_URL || "http://127.0.0.1:8000";
  const o = localStorage.getItem("backend_url_override");
  return o && o.trim() ? o.trim() : def;
}

/** 로그인 화면과 동일한 규칙: remember 시 localStorage + appBridge */
function usesPersistentTokenStorage() {
  return !!localStorage.getItem("accessToken") || !!localStorage.getItem("refreshToken");
}

async function persistDesktopTokens(data, email) {
  const remember = usesPersistentTokenStorage();
  const payload = {
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    email: email || "",
  };
  if (remember) {
    if (window.appBridge) {
      try {
        await window.appBridge.authSave(payload);
      } catch {
        /* ignore */
      }
    }
    localStorage.setItem("accessToken", data.access_token);
    localStorage.setItem("refreshToken", data.refresh_token);
    localStorage.setItem("email", email || "");
  } else {
    sessionStorage.setItem("accessToken", data.access_token);
    sessionStorage.setItem("refreshToken", data.refresh_token);
    sessionStorage.setItem("email", email || "");
  }
}

/**
 * JWT는 남아 있어도 서버 users.json 등이 초기화되면 /me 가 실패합니다.
 * refresh → 재저장까지 시도하고, 불가 시 세션을 지우고 이유를 돌려줍니다.
 */
async function ensureValidBackendSession(backendUrl) {
  const session = await resolveDesktopSession();
  if (!session || !session.accessToken) {
    return { ok: false, kind: "no_session", message: "저장된 로그인 정보가 없습니다." };
  }
  const base = String(backendUrl || effectiveBackendUrl()).replace(/\/$/, "");
  let res = await fetch(base + "/api/auth/me", {
    headers: { Authorization: "Bearer " + session.accessToken },
  });
  if (res.ok) {
    return { ok: true, kind: "ok" };
  }
  if (res.status === 401 && session.refreshToken) {
    const rr = await fetch(base + "/api/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: session.refreshToken }),
    });
    if (rr.ok) {
      const data = await rr.json();
      await persistDesktopTokens(data, session.email);
      return { ok: true, kind: "refreshed" };
    }
  }
  await clearDesktopSession();
  return {
    ok: false,
    kind: "server_session_invalid",
    message:
      "서버에 계정 데이터가 없거나 토큰이 더 이상 유효하지 않습니다. (배포 재시작·디스크 미연결 시 발생할 수 있음) 다시 회원가입/로그인하세요.",
  };
}

async function clearDesktopSession() {
  sessionStorage.removeItem("accessToken");
  sessionStorage.removeItem("refreshToken");
  sessionStorage.removeItem("email");
  localStorage.removeItem("accessToken");
  localStorage.removeItem("refreshToken");
  localStorage.removeItem("email");
  if (window.appBridge) {
    try {
      await window.appBridge.authClear();
    } catch {
      /* ignore */
    }
  }
}
