"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { apiFetch, bffFetch, getAccessToken, setAccessToken } from "@/lib/api-client";
import { useAuthStore, type AuthOrganization, type AuthUser } from "@/stores/auth-store";

interface MeResponse {
  user: AuthUser;
  organizations: AuthOrganization[];
  active_organization_id: string | null;
  permissions: string[];
}

/**
 * Client-side route protection for the console.
 *
 * On a fresh page load the access token is gone — it only ever lived in memory.
 * The refresh cookie survives, so this exchanges it for a new access token and
 * then loads the profile. That silent refresh is the one documented cost of
 * keeping the token out of localStorage (docs/05-architecture.md §6).
 *
 * This is UX, not security: it decides what to render. Every request is
 * independently authorized by the API.
 */
export function SessionGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const status = useAuthStore((state) => state.status);
  const setProfile = useAuthStore((state) => state.setProfile);
  const clear = useAuthStore((state) => state.clear);

  React.useEffect(() => {
    let cancelled = false;

    async function restore() {
      try {
        // Skip the refresh when a token is already in memory — this runs on
        // every console navigation, and rotating on each one would be wasteful
        // and would churn the token family.
        if (!getAccessToken()) {
          const { access_token } = await bffFetch<{ access_token: string }>("/api/auth/refresh");
          // Must be stored before the /me call below, which authenticates with it.
          setAccessToken(access_token);
        }

        const profile = await apiFetch<MeResponse>("/v1/console/auth/me");
        if (!cancelled) setProfile(profile);
      } catch {
        if (cancelled) return;
        clear();
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        router.replace(`/login?next=${next}`);
      }
    }

    void restore();
    return () => {
      cancelled = true;
    };
  }, [router, setProfile, clear]);

  if (status !== "authenticated") {
    return (
      <div className="flex min-h-dvh items-center justify-center" role="status" aria-live="polite">
        <Loader2 className="text-muted-foreground size-6 animate-spin" aria-hidden />
        <span className="sr-only">Loading your session…</span>
      </div>
    );
  }

  return <>{children}</>;
}
