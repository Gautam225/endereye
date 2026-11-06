import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiGet, refreshSession, setAccessToken, setSessionLostHandler } from "./api";

type Handler = (url: string, init: RequestInit) => Response;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "r1" },
  });
}

const session = (token: string) => ({
  access_token: token,
  token_type: "bearer",
  expires_in: 900,
  user: { id: "u1", email: "a@example.com", full_name: "A", role: "admin" },
});

const denied = (code: string) => json(401, { error: { code, message: code } });

let calls: Array<{ url: string; auth: string | null }>;

function mockFetch(handler: Handler) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, auth: new Headers(init.headers).get("Authorization") });
      return handler(url, init);
    }),
  );
}

beforeEach(() => {
  calls = [];
  setAccessToken("old-token");
  setSessionLostHandler(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("signed-in requests", () => {
  it("refreshes once on 401 and retries with the new token", async () => {
    mockFetch((url, init) => {
      if (url.endsWith("/auth/refresh")) return json(200, session("new-token"));
      const auth = new Headers(init.headers).get("Authorization");
      return auth === "Bearer new-token" ? json(200, { ok: true }) : denied("token_expired");
    });

    await expect(apiGet("/things")).resolves.toEqual({ ok: true });
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/things",
      "/api/v1/auth/refresh",
      "/api/v1/things",
    ]);
  });

  it("shares one refresh between requests that fail at the same time", async () => {
    mockFetch((url, init) => {
      if (url.endsWith("/auth/refresh")) return json(200, session("new-token"));
      const auth = new Headers(init.headers).get("Authorization");
      return auth === "Bearer new-token" ? json(200, { ok: true }) : denied("token_expired");
    });

    await Promise.all([apiGet("/a"), apiGet("/b"), apiGet("/c")]);
    expect(calls.filter((c) => c.url.endsWith("/auth/refresh"))).toHaveLength(1);
  });

  it("tries again once when another tab refreshed first", async () => {
    let refreshes = 0;
    mockFetch((url) => {
      if (!url.endsWith("/auth/refresh")) return json(200, {});
      refreshes += 1;
      return refreshes === 1 ? denied("refresh_superseded") : json(200, session("tab-token"));
    });

    await expect(refreshSession()).resolves.toMatchObject({ access_token: "tab-token" });
    expect(refreshes).toBe(2);
  });

  it("reports a lost session when the refresh fails", async () => {
    const lost = vi.fn();
    setSessionLostHandler(lost);
    mockFetch((url) =>
      url.endsWith("/auth/refresh") ? denied("session_expired") : denied("token_expired"),
    );

    await expect(apiGet("/things")).rejects.toMatchObject({ code: "token_expired", status: 401 });
    expect(lost).toHaveBeenCalledOnce();
  });
});
