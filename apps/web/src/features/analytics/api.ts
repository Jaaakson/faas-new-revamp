"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";

export interface MetricDelta {
  value: number;
  previous: number;
  change_pct: number | null;
  higher_is_better: boolean;
}

export interface Overview {
  verifications: MetricDelta;
  success_rate: MetricDelta;
  p95_latency_ms: MetricDelta;
  active_subjects: MetricDelta;
  period_days: number;
  has_any_data: boolean;
}

export interface TimeseriesPoint {
  day: string;
  verified: number;
  rejected: number;
  inconclusive: number;
  total: number;
}

export interface OutcomeSlice {
  decision: string;
  count: number;
  percentage: number;
}

export interface FailureReason {
  reason: string;
  count: number;
  percentage: number;
}

export interface LatencyDistribution {
  buckets: { bucket: string; count: number }[];
  p50: number;
  p95: number;
  p99: number;
}

export interface HourlyCell {
  weekday: number;
  hour: number;
  total: number;
  success_rate: number | null;
}

export interface Paginated<T> {
  data: T[];
  pagination: { next_cursor: string | null; has_more: boolean; limit: number };
}

export interface VerificationRow {
  id: string;
  subject_id: string | null;
  subject_external_id: string | null;
  decision: string;
  similarity: number | null;
  threshold_applied: number;
  confidence: string | null;
  failure_reason: string | null;
  latency_ms: number;
  source: string;
  created_at: string;
}

export interface SubjectRow {
  id: string;
  external_id: string;
  display_name: string | null;
  status: string;
  verification_count: number;
  enrolled_at: string | null;
  last_verified_at: string | null;
  created_at: string;
}

export interface AuditRow {
  id: string;
  actor_type: string;
  actor_email: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  changes: Record<string, unknown> | null;
  ip_address: string | null;
  request_id: string | null;
  created_at: string;
}

export interface AuthRow {
  id: string;
  email: string | null;
  event: string;
  success: boolean;
  ip_address: string | null;
  user_agent: string | null;
  detail: string | null;
  created_at: string;
}

/**
 * The active organization id, or "" while the session is still resolving.
 *
 * Every hook below gates on it via `enabled`, so no query can fire before the
 * tenant is known — which would otherwise cache a response under an empty key
 * and serve it to whichever org loaded next.
 */
function useOrgId(): string {
  return useAuthStore((state) => state.organization?.id ?? "");
}

export function useOverview(days: number) {
  const orgId = useOrgId();
  return useQuery({
    queryKey: queryKeys.overview(orgId, days),
    queryFn: () => api.get<Overview>(`/v1/console/analytics/overview?days=${days}`),
    enabled: !!orgId,
  });
}

export function useTimeseries(days: number) {
  const orgId = useOrgId();
  return useQuery({
    queryKey: queryKeys.timeseries(orgId, days),
    queryFn: () => api.get<TimeseriesPoint[]>(`/v1/console/analytics/timeseries?days=${days}`),
    enabled: !!orgId,
  });
}

export function useOutcomes(days: number) {
  const orgId = useOrgId();
  return useQuery({
    queryKey: queryKeys.outcomes(orgId, days),
    queryFn: () => api.get<OutcomeSlice[]>(`/v1/console/analytics/outcomes?days=${days}`),
    enabled: !!orgId,
  });
}

export function useFailureReasons(days: number) {
  const orgId = useOrgId();
  return useQuery({
    queryKey: queryKeys.failureReasons(orgId, days),
    queryFn: () => api.get<FailureReason[]>(`/v1/console/analytics/failure-reasons?days=${days}`),
    enabled: !!orgId,
  });
}

export function useLatency(days: number) {
  const orgId = useOrgId();
  return useQuery({
    queryKey: queryKeys.latency(orgId, days),
    queryFn: () => api.get<LatencyDistribution>(`/v1/console/analytics/latency?days=${days}`),
    enabled: !!orgId,
  });
}

export function useHourly(days: number) {
  const orgId = useOrgId();
  return useQuery({
    queryKey: queryKeys.hourly(orgId, days),
    queryFn: () => api.get<HourlyCell[]>(`/v1/console/analytics/hourly?days=${days}`),
    enabled: !!orgId,
  });
}

export function useVerifications(filters: {
  decision?: string;
  subject_id?: string;
  cursor?: string;
  limit?: number;
}) {
  const orgId = useOrgId();
  const params = new URLSearchParams();
  if (filters.decision) params.set("decision", filters.decision);
  if (filters.subject_id) params.set("subject_id", filters.subject_id);
  if (filters.cursor) params.set("cursor", filters.cursor);
  params.set("limit", String(filters.limit ?? 20));

  return useQuery({
    queryKey: queryKeys.verifications(orgId, filters),
    queryFn: () => api.get<Paginated<VerificationRow>>(`/v1/console/verifications?${params}`),
    enabled: !!orgId,
    // Keeps the previous page visible while the next loads, so paging does not
    // flash an empty table.
    placeholderData: (previous) => previous,
  });
}

export function useSubjects(filters: {
  status?: string;
  search?: string;
  cursor?: string;
  limit?: number;
}) {
  const orgId = useOrgId();
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.search) params.set("search", filters.search);
  if (filters.cursor) params.set("cursor", filters.cursor);
  params.set("limit", String(filters.limit ?? 20));

  return useQuery({
    queryKey: queryKeys.subjects(orgId, filters),
    queryFn: () => api.get<Paginated<SubjectRow>>(`/v1/console/subjects?${params}`),
    enabled: !!orgId,
    placeholderData: (previous) => previous,
  });
}

export function useAuditLog(filters: { action?: string; cursor?: string }) {
  const orgId = useOrgId();
  const params = new URLSearchParams();
  if (filters.action) params.set("action", filters.action);
  if (filters.cursor) params.set("cursor", filters.cursor);

  return useQuery({
    queryKey: queryKeys.auditLog(orgId, filters),
    queryFn: () => api.get<Paginated<AuditRow>>(`/v1/console/logs/audit?${params}`),
    enabled: !!orgId,
    placeholderData: (previous) => previous,
  });
}

export function useAuthLog(filters: { cursor?: string }) {
  const orgId = useOrgId();
  const params = new URLSearchParams();
  if (filters.cursor) params.set("cursor", filters.cursor);

  return useQuery({
    queryKey: queryKeys.authLog(orgId, filters),
    queryFn: () => api.get<Paginated<AuthRow>>(`/v1/console/logs/auth?${params}`),
    enabled: !!orgId,
    placeholderData: (previous) => previous,
  });
}
