"use client";

import { create } from "zustand";

import { setAccessToken } from "@/lib/api-client";

/**
 * Session state.
 *
 * Holds only *identity* — who is signed in and which organization is active.
 * Server data (members, subjects, verifications) belongs to TanStack Query.
 * The most common failure mode in React dashboards is a global store shadowing
 * the cache and drifting out of sync, so the boundary is enforced by scope:
 * nothing fetched from a list endpoint is allowed in here.
 *
 * The access token itself is deliberately NOT in this store — it lives in a
 * module closure in api-client so it never enters React state, devtools, or a
 * serialized snapshot.
 */

export interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
  email_verified: boolean;
}

export interface AuthOrganization {
  id: string;
  name: string;
  slug: string;
  plan: string;
  role: string;
}

interface AuthState {
  user: AuthUser | null;
  organization: AuthOrganization | null;
  organizations: AuthOrganization[];
  permissions: string[];
  status: "loading" | "authenticated" | "anonymous";

  setSession: (session: {
    access_token: string;
    user: AuthUser;
    organization: AuthOrganization | null;
  }) => void;
  setProfile: (profile: {
    user: AuthUser;
    organizations: AuthOrganization[];
    active_organization_id: string | null;
    permissions: string[];
  }) => void;
  clear: () => void;
  /** Mirrors the server check. UX only — the server enforces independently. */
  can: (permission: string) => boolean;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  organization: null,
  organizations: [],
  permissions: [],
  status: "loading",

  setSession: ({ access_token, user, organization }) => {
    setAccessToken(access_token);
    set({ user, organization, status: "authenticated" });
  },

  setProfile: ({ user, organizations, active_organization_id, permissions }) =>
    set({
      user,
      organizations,
      organization: organizations.find((org) => org.id === active_organization_id) ?? null,
      permissions,
      status: "authenticated",
    }),

  clear: () => {
    setAccessToken(null);
    set({
      user: null,
      organization: null,
      organizations: [],
      permissions: [],
      status: "anonymous",
    });
  },

  can: (permission) => get().permissions.includes(permission),
}));
