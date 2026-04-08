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
