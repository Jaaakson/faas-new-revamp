import { NextResponse, type NextRequest } from "next/server";

import { setRefreshCookie } from "@/lib/auth/cookies";
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
 * Sign in.
 *
 * Proxies to the API, then moves the refresh token into an httpOnly cookie and
 * strips it from the response body. The browser gets only the short-lived
 * access token.
 */
export async function POST(request: NextRequest) {
  let upstream: Response;
  try {
    upstream = await callApi("/v1/console/auth/login", {
      method: "POST",
      body: JSON.stringify(await request.json()),
      requestId: request.headers.get("x-request-id"),
    });
  } catch {
    return unreachable();
  }

  if (!upstream.ok) return forwardError(upstream);

  const session = (await upstream.json()) as SessionPayload;
  const response = NextResponse.json(withoutRefreshToken(session));
  setRefreshCookie(response, session.refresh_token);
  return response;
}
