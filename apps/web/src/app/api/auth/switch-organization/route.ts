import { NextResponse, type NextRequest } from "next/server";

import { REFRESH_COOKIE, setRefreshCookie } from "@/lib/auth/cookies";
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
 * Switch the active organization.
 *
 * Goes through the BFF because it rotates the refresh token — the browser never
 * holds one, so it cannot make this call itself.
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

  const body = (await request.json()) as { organization_id?: string };

  let upstream: Response;
  try {
    upstream = await callApi("/v1/console/auth/switch-organization", {
      method: "POST",
      body: JSON.stringify({
        refresh_token: refreshToken,
        organization_id: body.organization_id,
      }),
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
