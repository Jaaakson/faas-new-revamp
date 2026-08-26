import { NextResponse } from "next/server";

/**
 * Shared helpers for the BFF route handlers.
 *
 * The BFF is deliberately narrow: it proxies only the auth calls that must
 * touch the httpOnly refresh cookie. Everything else goes browser → API
 * directly with a bearer token, so this file never grows into a second API.
 */

/**
 * Where the BFF reaches the API from.
 *
 * This runs on the *server*, so it must not reuse `NEXT_PUBLIC_API_URL` — that
 * value is the browser's view of the API. Under Docker the browser reaches it
 * on a published port (`http://localhost:8000`) while the container reaches it
 * by service name (`http://api:8000`); using the browser's URL server-side
 * resolves to the web container itself and every auth call fails with
 * `upstream_unavailable`.
 *
 * `API_INTERNAL_URL` carries no NEXT_PUBLIC_ prefix on purpose: it is
 * server-only and must never be inlined into the client bundle. It falls back
 * to the public URL so running both apps directly on the host still works.
 */
const API_URL =
  process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface SessionPayload {
  access_token: string;
  refresh_token: string;
  expires_at: string;
  user: unknown;
  organization: unknown;
}

/** Call the upstream API, forwarding the caller's tracing headers. */
export async function callApi(
  path: string,
  init: RequestInit & { requestId?: string | null } = {},
): Promise<Response> {
  const { requestId, ...rest } = init;

  return fetch(`${API_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(requestId ? { "X-Request-ID": requestId } : {}),
      ...rest.headers,
    },
    // Never cache an auth response.
    cache: "no-store",
  });
}

/**
 * Strip the refresh token from a session body before it reaches the browser.
 *
 * The API returns it so the BFF can put it in a cookie. If it also reached
 * JavaScript, the httpOnly cookie would be pointless — the token would be
 * readable exactly where we were trying to keep it out of.
 */
export function withoutRefreshToken(payload: SessionPayload) {
  const { refresh_token: _discarded, ...safe } = payload;
  return safe;
}

/** Pass an upstream error through unchanged, preserving the error envelope. */
export async function forwardError(response: Response): Promise<NextResponse> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = {
      error: {
        code: "upstream_unavailable",
        message: "The authentication service is unavailable.",
        details: null,
        request_id: null,
      },
    };
  }
  return NextResponse.json(body, { status: response.status });
}

/** The API being unreachable is an infrastructure failure, not a client error. */
export function unreachable(): NextResponse {
  return NextResponse.json(
    {
      error: {
        code: "upstream_unavailable",
        message: "Could not reach the authentication service. Please try again.",
        details: null,
        request_id: null,
      },
    },
    { status: 503 },
  );
}
