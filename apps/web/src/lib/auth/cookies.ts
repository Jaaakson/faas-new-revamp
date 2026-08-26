import type { NextResponse } from "next/server";

/**
 * Refresh-token cookie handling.
 *
 * The refresh token is the long-lived credential, so it lives in an httpOnly
 * cookie that JavaScript cannot read — an XSS in the console must not be able
 * to steal a 30-day session. The short-lived access token stays in memory,
 * where an XSS could reach it but only for 15 minutes.
 *
 * This split is the whole reason a BFF exists here: only these route handlers
 * ever touch the cookie (docs/05-architecture.md §6).
 */

export const REFRESH_COOKIE = "fvas_refresh";

const THIRTY_DAYS_SECONDS = 60 * 60 * 24 * 30;

export function setRefreshCookie(response: NextResponse, token: string): void {
  response.cookies.set({
    name: REFRESH_COOKIE,
    value: token,
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    // Lax, not Strict: Strict would drop the cookie when a user arrives from an
    // email link, silently signing them out at the worst moment. Lax still
    // blocks cross-site POSTs, which is the CSRF vector that matters.
    sameSite: "lax",
    // Scoped to the refresh endpoint so it is not attached to every request.
    path: "/",
    maxAge: THIRTY_DAYS_SECONDS,
  });
}

export function clearRefreshCookie(response: NextResponse): void {
  response.cookies.set({
    name: REFRESH_COOKIE,
    value: "",
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
}
