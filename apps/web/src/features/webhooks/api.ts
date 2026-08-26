"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";

export const WEBHOOK_EVENTS = [
  "verification.completed",
  "verification.failed",
  "enrollment.completed",
  "enrollment.duplicate_detected",
  "subject.deleted",
  "quota.threshold_reached",
] as const;

export interface WebhookEndpoint {
  id: string;
  url: string;
  description: string | null;
  events: string[];
  is_active: boolean;
  failure_count: number;
  disabled_at: string | null;
  last_delivery_at: string | null;
  created_at: string;
  secret_hint: string;
}

export interface WebhookWithSecret extends WebhookEndpoint {
  /** Returned once, at creation and rotation. Never retrievable afterwards. */
  secret: string;
}

export interface WebhookDelivery {
  id: string;
  endpoint_id: string;
  event_type: string;
  event_id: string;
  status: "pending" | "delivered" | "failed";
  attempt_count: number;
  response_status: number | null;
  error: string | null;
  next_retry_at: string | null;
  delivered_at: string | null;
  created_at: string;
}

function useOrgId(): string {
  return useAuthStore((state) => state.organization?.id ?? "");
}

export function useWebhooks() {
  const orgId = useOrgId();
  return useQuery({
    queryKey: queryKeys.webhooks(orgId),
    queryFn: () => api.get<WebhookEndpoint[]>("/v1/console/webhooks"),
    enabled: !!orgId,
  });
}

export function useWebhookDeliveries(endpointId: string | null) {
  const orgId = useOrgId();
  return useQuery({
    queryKey: queryKeys.webhookDeliveries(orgId, endpointId ?? ""),
    queryFn: () =>
      api.get<WebhookDelivery[]>(`/v1/console/webhooks/${endpointId}/deliveries?limit=25`),
    enabled: !!orgId && !!endpointId,
  });
}

function useInvalidate() {
  const orgId = useOrgId();
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: queryKeys.webhooks(orgId) });
}

export function useCreateWebhook() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (input: { url: string; events: string[]; description?: string | null }) =>
      api.post<WebhookWithSecret>("/v1/console/webhooks", input),
    onSuccess: invalidate,
  });
}

export function useUpdateWebhook() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, ...input }: { id: string; is_active?: boolean; events?: string[] }) =>
      api.patch<WebhookEndpoint>(`/v1/console/webhooks/${id}`, input),
    onSuccess: invalidate,
  });
}

export function useDeleteWebhook() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.delete<{ deleted: boolean }>(`/v1/console/webhooks/${id}`),
    onSuccess: invalidate,
  });
}

export function useRotateSecret() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<WebhookWithSecret>(`/v1/console/webhooks/${id}/rotate`),
    onSuccess: invalidate,
  });
}

export function useTestWebhook() {
  const orgId = useOrgId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<WebhookDelivery>(`/v1/console/webhooks/${id}/test`),
    onSuccess: (_result, id) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.webhookDeliveries(orgId, id),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.webhooks(orgId) });
    },
  });
}
