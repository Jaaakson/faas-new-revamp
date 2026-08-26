import type { ApiErrorBody } from "@fvas/shared";

/**
 * The browser's API client.
 *
 * Two responsibilities that are easy to get subtly wrong:
 *
 * 1. **The access token lives in memory only.** Not localStorage, not a
 *    readable cookie. A closure variable dies with the tab, which is exactly
 *    what we want from a credential an XSS could otherwise exfiltrate.
 *
 * 2. **A 401 triggers one silent refresh and replays the original request.**
 *    Concurrent 401s share a single in-flight refresh — without that,
 *    ten parallel requests would fire ten rotations, and refresh-token rotation
 *    means nine of them would be treated as *reuse* and revoke the family.
 *    That failure mode logs the user out for doing nothing wrong.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: Record<string, unknown> | null,
    readonly requestId?: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** True when retrying the identical request could plausibly succeed. */
  get isRetryable(): boolean {
    return this.status === 429 || this.status >= 500;
  }
}

let accessToken: string | null = null;
let onSessionExpired: (() => void) | null = null;

/** Shared in-flight refresh, so parallel 401s rotate the token exactly once. */
let refreshInFlight: Promise<string | null> | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setSessionExpiredHandler(handler: (() => void) | null): void {
  onSessionExpired = handler;
}

async function refreshAccessToken(): Promise<string | null> {
  refreshInFlight ??= (async () => {
    try {
      // The BFF, not the API: the refresh token is in an httpOnly cookie that
      // only a same-origin route handler can read.
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok) return null;

      const session = (await response.json()) as { access_token: string };
      accessToken = session.access_token;
      return session.access_token;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Internal: prevents a refreshed request from recursing on another 401. */
  _isRetry?: boolean;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, _isRetry = false, headers, ...rest } = options;

  const response = await fetch(`${API_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401 && !_isRetry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      // Replay the original request. From the caller's perspective the token
      // expiry never happened.
      return apiFetch<T>(path, { ...options, _isRetry: true });
    }
    accessToken = null;
    onSessionExpired?.();
  }

  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const envelope = payload as ApiErrorBody | null;
    throw new ApiError(
      response.status,
      envelope?.error?.code ?? "unknown_error",
      envelope?.error?.message ?? "Something went wrong.",
      envelope?.error?.details,
      envelope?.error?.request_id ?? response.headers.get("x-request-id"),
    );
  }

  return payload as T;
}

/** Auth calls that must go through the BFF because they touch the cookie. */
export async function bffFetch<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    credentials: "include",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const envelope = payload as ApiErrorBody | null;
    throw new ApiError(
      response.status,
      envelope?.error?.code ?? "unknown_error",
      envelope?.error?.message ?? "Something went wrong.",
      envelope?.error?.details,
      envelope?.error?.request_id,
    );
  }

  return payload as T;
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) => apiFetch<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body?: unknown) => apiFetch<T>(path, { method: "PATCH", body }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: "DELETE" }),
};
