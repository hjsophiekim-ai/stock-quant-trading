const test = require("node:test");
const assert = require("node:assert/strict");

function b64url(obj) {
  const json = JSON.stringify(obj);
  const b64 = Buffer.from(json, "utf8").toString("base64");
  return b64.replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}

function makeJwt(expSec) {
  return [b64url({ alg: "HS256", typ: "JWT" }), b64url({ exp: expSec }), "sig"].join(".");
}

function makeStorage() {
  const m = new Map();
  return {
    getItem(k) {
      return m.has(k) ? m.get(k) : null;
    },
    setItem(k, v) {
      m.set(k, String(v));
    },
    removeItem(k) {
      m.delete(k);
    },
    _dump() {
      return Object.fromEntries(m.entries());
    },
  };
}

test("authFetch single-flights refresh", async () => {
  globalThis.atob = globalThis.atob || ((s) => Buffer.from(s, "base64").toString("binary"));
  globalThis.window = { RUNTIME_CONFIG: { BACKEND_URL: "http://backend" }, location: { href: "" } };
  globalThis.localStorage = makeStorage();
  globalThis.sessionStorage = makeStorage();

  const nowSec = Math.floor(Date.now() / 1000);
  localStorage.setItem("accessToken", makeJwt(nowSec - 10));
  localStorage.setItem("refreshToken", "r1");
  localStorage.setItem("email", "u@example.com");

  let refreshCalls = 0;
  globalThis.fetch = async (url, init) => {
    const u = String(url);
    if (u.endsWith("/api/auth/refresh")) {
      refreshCalls += 1;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          access_token: makeJwt(nowSec + 3600),
          refresh_token: "r2",
        }),
      };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ ok: true, url: u, headers: init?.headers || {} }),
    };
  };

  require("../src/auth-session.js");

  await Promise.all([
    globalThis.authFetch("http://backend/api/x"),
    globalThis.authFetch("http://backend/api/y"),
  ]);

  assert.equal(refreshCalls, 1);
});

test("authFetch retries once on 401", async () => {
  globalThis.atob = globalThis.atob || ((s) => Buffer.from(s, "base64").toString("binary"));
  globalThis.window = { RUNTIME_CONFIG: { BACKEND_URL: "http://backend" }, location: { href: "" } };
  globalThis.localStorage = makeStorage();
  globalThis.sessionStorage = makeStorage();

  const nowSec = Math.floor(Date.now() / 1000);
  localStorage.setItem("accessToken", makeJwt(nowSec + 3600));
  localStorage.setItem("refreshToken", "r1");
  localStorage.setItem("email", "u@example.com");

  let first = true;
  let refreshCalls = 0;
  globalThis.fetch = async (url, init) => {
    const u = String(url);
    if (u.endsWith("/api/auth/refresh")) {
      refreshCalls += 1;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          access_token: makeJwt(nowSec + 7200),
          refresh_token: "r2",
        }),
      };
    }
    if (u.endsWith("/api/protected") && first) {
      first = false;
      return { ok: false, status: 401, json: async () => ({ detail: "Invalid or expired token" }) };
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  };

  require("../src/auth-session.js");

  const res = await globalThis.authFetch("http://backend/api/protected");
  assert.equal(res.status, 200);
  assert.equal(refreshCalls, 1);
});

