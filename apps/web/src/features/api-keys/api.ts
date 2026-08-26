"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";

export interface ApiKey {
  id: string;
  name: string;
  environment: string;
  key_prefix: string;
  last4: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  rotated_at: string | null;
  ip_allowlist: string | null;
  status: string;
}

/** The only shape that ever carries the secret. */
export interface ApiKeyCreated extends ApiKey {
  secret: string;
}

export interface ApiKeyInput {
  name: string;
  environment: string;
  scopes?: string[];
  expires_at?: string | null;
  ip_allowlist?: string | null;
}

/** Every scope a key can hold, with copy explaining what it actually permits. */
export const SCOPES = [
  { value: "subject:read", label: "Read subjects", detail: "List and retrieve your end users." },
  { value: "subject:write", label: "Write subjects", detail: "Create and update end users." },
  {
    value: "subject:delete",
    label: "Delete subjects",
    detail: "Permanently destroy a subject and its biometric templates.",
  },
  {
    value: "enrollment:write",
    label: "Enroll faces",
    detail: "Create and replace face profiles.",
  },
  {
    value: "verification:write",
    label: "Verify faces",
    detail: "The core call. Consumes your monthly quota.",
  },
  { value: "verification:read", label: "Read verifications", detail: "List and inspect sessions." },
] as const;

function useOrgId(): string {
  return useAuthStore((state) => state.organization?.id ?? "");
}

export function useApiKeys() {
  const orgId = useOrgId();
  return useQuery({
    queryKey: queryKeys.apiKeys(orgId),
    queryFn: () => api.get<ApiKey[]>("/v1/console/api-keys"),
    enabled: !!orgId,
  });
}

export function useCreateApiKey() {
  const orgId = useOrgId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ApiKeyInput) => api.post<ApiKeyCreated>("/v1/console/api-keys", input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys(orgId) });
    },
  });
}

export function useRotateApiKey() {
  const orgId = useOrgId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) =>
      api.post<ApiKeyCreated>(`/v1/console/api-keys/${keyId}/rotate`, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys(orgId) });
    },
  });
}

export function useRevokeApiKey() {
  const orgId = useOrgId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) =>
      api.delete<{ revoked: boolean }>(`/v1/console/api-keys/${keyId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys(orgId) });
    },
  });
}
