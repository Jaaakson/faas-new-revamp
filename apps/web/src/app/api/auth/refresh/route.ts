import { NextResponse, type NextRequest } from "next/server";

import { REFRESH_COOKIE, clearRefreshCookie, setRefreshCookie } from "@/lib/auth/cookies";
import {
  callApi,
  forwardError,
  unreachable,
  withoutRefreshToken,
  type SessionPayload,
} from "@/lib/auth/upstream";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Rotate the session.
 *
 * The browser sends no body — the token comes from the cookie it cannot read.
 * That is what makes a stolen access token useless for extending a session: an
 * attacker with XSS can call this endpoint, but only from the victim's browser,
 * and only while the victim is still signed in.
 */
export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;

  if (!refreshToken) {
    return NextResponse.json(
      {
        error: {
          code: "unauthenticated",
          message: "No active session.",
          details: null,
          request_id: null,
        },
      },
      { status: 401 },
    );
  }

  let upstream: Response;
  try {
    upstream = await callApi("/v1/console/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
      requestId: request.headers.get("x-request-id"),
    });
  } catch {
    return unreachable();
  }

  if (!upstream.ok) {
    // The token is expired, revoked, or was replayed. Clear the cookie so the
    // browser stops retrying with a credential that will never work again.
    const error = await forwardError(upstream);
    clearRefreshCookie(error);
    return error;
  }

  const session = (await upstream.json()) as SessionPayload;
  const response = NextResponse.json(withoutRefreshToken(session));
  setRefreshCookie(response, session.refresh_token);
  return response;
}
