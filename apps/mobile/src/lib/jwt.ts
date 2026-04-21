export type JwtPayload = {
  exp?: number;
  [k: string]: unknown;
};

function b64UrlToUtf8(b64Url: string): string {
  const b64 = b64Url.replace(/-/g, "+").replace(/_/g, "/");
  const padLen = (4 - (b64.length % 4)) % 4;
  const padded = b64 + "=".repeat(padLen);
  let binary = "";
  // eslint-disable-next-line no-undef
  if (typeof atob === "function") {
    binary = atob(padded);
  } else {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    binary = require("base-64").decode(padded) as string;
  }
  let out = "";
  for (let i = 0; i < binary.length; i++) {
    out += String.fromCharCode(binary.charCodeAt(i));
  }
  try {
    return decodeURIComponent(
      out
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join(""),
    );
  } catch {
    return out;
  }
}

export function decodeJwtPayload(token: string): JwtPayload | null {
  const t = String(token || "").trim();
  if (!t) return null;
  const parts = t.split(".");
  if (parts.length < 2) return null;
  try {
    const json = b64UrlToUtf8(parts[1] || "");
    const payload = JSON.parse(json) as JwtPayload;
    if (!payload || typeof payload !== "object") return null;
    return payload;
  } catch {
    return null;
  }
}

export function jwtExpEpochSec(token: string): number | null {
  const p = decodeJwtPayload(token);
  const exp = p?.exp;
  return typeof exp === "number" && Number.isFinite(exp) ? exp : null;
}

export function jwtExpiresInSec(token: string, nowEpochMs: number = Date.now()): number | null {
  const exp = jwtExpEpochSec(token);
  if (exp == null) return null;
  const nowSec = Math.floor(nowEpochMs / 1000);
  return exp - nowSec;
}
