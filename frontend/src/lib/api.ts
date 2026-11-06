/**
 * Talks to the FastAPI backend. In development Vite proxies /api to it (see vite.config.ts).
 * Every backend error has the shape {"error": {code, message, request_id, details}}.
 *
 * Sign-in: the access token lives only in memory (here). The refresh token is an httpOnly
 * cookie the browser sends to /api/v1/auth by itself. When a request gets a 401, the client
 * refreshes once and retries; if that fails, the session is over.
 */

const BASE = "/api/v1";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor(
    message: string,
    options: { code: string; status: number; requestId?: string | null; details?: unknown },
  ) {
    super(message);
    this.name = "ApiError";
    this.code = options.code;
    this.status = options.status;
    this.requestId = options.requestId ?? null;
    this.details = options.details ?? null;
  }

  /** Seconds to wait before retrying, when the backend says so. */
  get retryAfter(): number | null {
    const value = (this.details as { retry_after?: unknown } | null)?.retry_after;
    return typeof value === "number" ? value : null;
  }

  /** Field-level messages from a 422 response, keyed by field name ("password"). */
  get fieldErrors(): Record<string, string> {
    if (this.code !== "validation_error" || !Array.isArray(this.details)) return {};
    const errors: Record<string, string> = {};
    for (const item of this.details as Array<{ field?: string; message?: string }>) {
      const name = item.field?.split(".").pop();
      if (name && item.message && !errors[name]) errors[name] = item.message;
    }
    return errors;
  }
}

/** Anything a request threw, as an ApiError (for showing its message). */
export function asApiError(caught: unknown): ApiError {
  return caught instanceof ApiError
    ? caught
    : new ApiError("Something went wrong.", { code: "error", status: 0 });
}

export const BACKEND_UNREACHABLE =
  "Can't reach the backend. Start it from the backend folder with: uvicorn app.main:app --reload";

/** Turn a failed response into an ApiError, whatever its body looks like. */
export async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("X-Request-ID");
  try {
    const body = (await response.json()) as {
      error?: { code?: string; message?: string; details?: unknown };
    };
    if (body.error?.message) {
      return new ApiError(body.error.message, {
        code: body.error.code ?? "error",
        status: response.status,
        requestId,
        details: body.error.details,
      });
    }
  } catch {
    // Not our JSON: usually the dev proxy answering because the backend is down.
  }
  const unreachable = response.status === 502 || response.status === 503 || response.status === 504;
  return new ApiError(unreachable || !requestId ? BACKEND_UNREACHABLE : response.statusText, {
    code: unreachable || !requestId ? "backend_unreachable" : "http_error",
    status: response.status,
    requestId,
  });
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${BASE}${path}`, { credentials: "same-origin", ...init });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(BACKEND_UNREACHABLE, { code: "backend_unreachable", status: 0 });
  }
}

async function readJson<T>(response: Response): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(BACKEND_UNREACHABLE, {
      code: "backend_unreachable",
      status: response.status,
    });
  }
}

// ── Session ──────────────────────────────────────────────────────────────────

export type Role = "admin" | "editor" | "viewer";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Session {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

let accessToken: string | null = null;
let refreshing: Promise<Session | null> | null = null;
let onSessionLost: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** Called when a refresh fails mid-use: the app shows the sign-in page. */
export function setSessionLostHandler(handler: (() => void) | null): void {
  onSessionLost = handler;
}

/**
 * Get a new access token from the refresh cookie. Concurrent callers share one request.
 * Returns null when there is no valid session.
 */
export function refreshSession(): Promise<Session | null> {
  refreshing ??= (async () => {
    try {
      for (let attempt = 0; attempt < 2; attempt++) {
        const response = await send("/auth/refresh", { method: "POST" });
        if (response.ok) {
          const session = await readJson<Session>(response);
          accessToken = session.access_token;
          return session;
        }
        const error = await toApiError(response);
        if (error.code === "refresh_superseded" && attempt === 0) {
          // Another tab refreshed a moment ago; the browser now holds the newer cookie.
          await new Promise((resolve) => setTimeout(resolve, 250));
          continue;
        }
        if (error.status === 401) break;
        throw error;
      }
      accessToken = null;
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

/** A request with the access token; on 401 it refreshes once and retries. */
async function authed(path: string, init: RequestInit = {}): Promise<Response> {
  const attempt = () => {
    const headers = new Headers(init.headers);
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    return send(path, { ...init, headers });
  };
  const response = await attempt();
  if (response.status !== 401) return response;
  if (await refreshSession()) return attempt();
  onSessionLost?.();
  return response;
}

// ── Requests ─────────────────────────────────────────────────────────────────

export async function apiGet<T>(path: string, options?: { okStatuses?: number[] }): Promise<T> {
  const response = await authed(path, { headers: { Accept: "application/json" } });
  const ok = response.ok || options?.okStatuses?.includes(response.status);
  if (!ok) throw await toApiError(response);
  return readJson<T>(response);
}

/** A file download: the body as a Blob, and the file name the server suggested. */
export async function apiBlob(path: string): Promise<{ blob: Blob; filename: string }> {
  const response = await authed(path);
  if (!response.ok) throw await toApiError(response);
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  return { blob: await response.blob(), filename: match?.[1] ?? "download" };
}

export async function apiSend<T>(
  method: "POST" | "PATCH" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await authed(path, {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await toApiError(response);
  return response.status === 204 ? (undefined as T) : readJson<T>(response);
}

/**
 * Multipart POST with upload progress (0..1), which fetch can't report, so this uses XHR.
 * Like the other requests, it refreshes once and retries on a 401.
 */
export async function apiUpload<T>(
  path: string,
  form: FormData,
  onProgress?: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<T> {
  const attempt = () =>
    new Promise<Response>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}${path}`);
      xhr.setRequestHeader("Accept", "application/json");
      if (accessToken) xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress?.(event.loaded / event.total);
      };
      xhr.onload = () => {
        const headers = new Headers({
          "Content-Type": xhr.getResponseHeader("Content-Type") ?? "",
          "X-Request-ID": xhr.getResponseHeader("X-Request-ID") ?? "",
        });
        const empty = xhr.status === 204 || !xhr.responseText;
        resolve(new Response(empty ? null : xhr.responseText, { status: xhr.status, headers }));
      };
      xhr.onerror = () =>
        reject(new ApiError(BACKEND_UNREACHABLE, { code: "backend_unreachable", status: 0 }));
      xhr.onabort = () => reject(new DOMException("The upload was cancelled.", "AbortError"));
      signal?.addEventListener("abort", () => xhr.abort(), { once: true });
      xhr.send(form);
    });

  let response = await attempt();
  if (response.status === 401) {
    if (await refreshSession()) response = await attempt();
    else onSessionLost?.();
  }
  if (!response.ok) throw await toApiError(response);
  return readJson<T>(response);
}

/** For sign-in endpoints: no access token, no automatic refresh. */
export async function publicSend<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await send(path, {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await toApiError(response);
  return response.status === 204 ? (undefined as T) : readJson<T>(response);
}

/** POST that answers with Server-Sent Events. Returns the response once headers arrive. */
export async function apiPostStream(
  path: string,
  body: unknown,
  signal: AbortSignal,
): Promise<Response> {
  return openStream(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
}

/** GET that answers with Server-Sent Events, to rejoin something already running. */
export async function apiGetStream(path: string, signal: AbortSignal): Promise<Response> {
  return openStream(path, { headers: { Accept: "text/event-stream" }, signal });
}

async function openStream(path: string, init: RequestInit): Promise<Response> {
  const response = await authed(path, init);
  if (!response.ok) throw await toApiError(response);
  if (!response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
    throw new ApiError(BACKEND_UNREACHABLE, {
      code: "backend_unreachable",
      status: response.status,
    });
  }
  return response;
}
