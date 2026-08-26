import { NextResponse, type NextRequest } from "next/server";

import { REFRESH_COOKIE, clearRefreshCookie } from "@/lib/auth/cookies";
import { callApi } from "@/lib/auth/upstream";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Sign out.
 *
 * Always clears the cookie, even when the upstream revoke fails. A user who
 * clicked "sign out" must end up signed out locally regardless — leaving the
 * cookie in place because the network hiccuped would be the worst possible
 * outcome on a shared machine.
 */
export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  const accessToken = request.headers.get("authorization");

  if (refreshToken && accessToken) {
    try {
      await callApi("/v1/console/auth/logout", {
        method: "POST",
        headers: { Authorization: accessToken },
        body: JSON.stringify({ refresh_token: refreshToken }),
        requestId: request.headers.get("x-request-id"),
      });
    } catch {
      // Best effort. The cookie is cleared below either way.
    }
  }

  const response = NextResponse.json({ message: "Signed out." });
  clearRefreshCookie(response);
  return response;
}
