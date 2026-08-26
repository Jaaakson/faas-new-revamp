import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The BFF's upstream address.
 *
 * Regression cover for a bug that only appeared under Docker: the route
 * handlers run server-side, so reusing the browser-facing `NEXT_PUBLIC_API_URL`
 * made them resolve `localhost` to the web container itself and every auth call
 * failed with `upstream_unavailable`. The module reads the URL once at import,
 * so each case re-imports it with a fresh environment.
 */
async function loadWithEnv(env: Record<string, string | undefined>) {
  vi.resetModules();
  for (const [key, value] of Object.entries(env)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  return import("./upstream");
}

const ORIGINAL = { ...process.env };

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 200 })),
  );
});

afterEach(() => {
  process.env = { ...ORIGINAL };
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("BFF upstream URL", () => {
  it("prefers the server-only internal URL", async () => {
    const { callApi } = await loadWithEnv({
      API_INTERNAL_URL: "http://api:8000",
      NEXT_PUBLIC_API_URL: "http://localhost:8000",
    });

    await callApi("/v1/console/auth/login", { method: "POST" });

    // Docker: the browser sees localhost, the container must use the service name.
    expect(fetch).toHaveBeenCalledWith("http://api:8000/v1/console/auth/login", expect.anything());
  });

  it("falls back to the public URL when no internal URL is set", async () => {
    const { callApi } = await loadWithEnv({
      API_INTERNAL_URL: undefined,
      NEXT_PUBLIC_API_URL: "http://localhost:8000",
    });

    await callApi("/v1/console/auth/refresh", { method: "POST" });

    // Running both apps directly on the host must keep working.
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/v1/console/auth/refresh",
      expect.anything(),
    );
  });

  it("never caches an auth response", async () => {
    const { callApi } = await loadWithEnv({ API_INTERNAL_URL: "http://api:8000" });

    await callApi("/v1/console/auth/login", { method: "POST" });

    expect(fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("forwards the caller's request id for tracing", async () => {
    const { callApi } = await loadWithEnv({ API_INTERNAL_URL: "http://api:8000" });

    await callApi("/v1/console/auth/login", {
      method: "POST",
      requestId: "req_01HQZX8K4M2N",
    });

    expect(fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({ "X-Request-ID": "req_01HQZX8K4M2N" }),
      }),
    );
  });
});

describe("withoutRefreshToken", () => {
  it("strips the refresh token from anything returned to the browser", async () => {
    const { withoutRefreshToken } = await loadWithEnv({});

    const stripped = withoutRefreshToken({
      access_token: "at",
      refresh_token: "rt",
      expires_at: "2026-08-01T00:00:00Z",
      user: { id: "usr_1" },
      organization: { id: "org_1" },
    });

    // The refresh token lives only in the httpOnly cookie. Leaking it into the
    // JSON body would hand it to any script on the page.
    expect(stripped).not.toHaveProperty("refresh_token");
    expect(stripped).toHaveProperty("access_token", "at");
  });
});
