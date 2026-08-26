"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import { ApiError, api } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";

export interface GateCheck {
  check: string;
  passed: boolean;
  score: number;
  value: number;
  required: number;
}

export interface QualitySummary {
  score: number;
  sharpness: number;
  brightness: number;
  face_size_px: number;
  pose: { yaw: number; pitch: number; roll: number };
  checks: GateCheck[];
}

export interface LivenessSummary {
  evaluated: boolean;
  passed: boolean;
  score: number;
  signals: { signal: string; score: number; passed: boolean; required: number }[];
}

export interface VerificationResult {
  id: string;
  decision: "verified" | "rejected" | "inconclusive" | "error";
  subject_id: string | null;
  similarity: number | null;
  threshold: number;
  confidence: "high" | "medium" | "low" | null;
  failure_reason: string | null;
  guidance: string | null;
  templates_compared: number;
  quality: QualitySummary | null;
  liveness: LivenessSummary | null;
  timing: {
    total_ms: number;
    detect_ms: number | null;
    embed_ms: number | null;
    match_ms: number | null;
  };
  created_at: string;
}

export interface VerificationDetail extends Omit<VerificationResult, "timing" | "threshold"> {
  subject_external_id: string | null;
  threshold_applied: number;
  latency_ms: number;
  detect_ms: number | null;
  embed_ms: number | null;
  match_ms: number | null;
  source: string;
  ip_address: string | null;
  user_agent: string | null;
}

export interface ThresholdInfo {
  preset: string;
  threshold: number;
  far: number | null;
  frr: number | null;
  measured: boolean;
  intent: string | null;
  note: string | null;
}

function useOrgId(): string {
  return useAuthStore((state) => state.organization?.id ?? "");
}

/**
 * Running a verification is a mutation, and it is deliberately not retried.
 *
 * Every outcome except a transport failure is a *result*, not an error: a
 * rejection is a 200, and a 429 means the quota is gone and will still be gone
 * a second later. Retrying would only burn quota.
 */
export function useVerify() {
  return useMutation<
    VerificationResult,
    ApiError,
    {
      subject_id: string;
      image: string;
      options?: { threshold?: number; require_liveness?: boolean };
    }
  >({
    mutationFn: (input) => api.post<VerificationResult>("/v1/console/verifications", input),
    retry: false,
  });
}

export function useVerification(verificationId: string) {
  const orgId = useOrgId();
  return useQuery({
    queryKey: queryKeys.verification(orgId, verificationId),
    queryFn: () => api.get<VerificationDetail>(`/v1/console/verifications/${verificationId}`),
    enabled: !!orgId && !!verificationId,
  });
}

export function useThresholdInfo() {
  const orgId = useOrgId();
  return useQuery({
    queryKey: queryKeys.threshold(orgId),
    queryFn: () => api.get<ThresholdInfo>("/v1/console/threshold"),
    enabled: !!orgId,
  });
}

/** Copy for a decision. The three-way outcome is the product's core contract. */
export const DECISION_COPY: Record<string, { label: string; blurb: string }> = {
  verified: { label: "Verified", blurb: "Similarity met or exceeded the threshold." },
  rejected: {
    label: "Rejected",
    blurb: "A real face, but not this person.",
  },
  inconclusive: {
    label: "Inconclusive",
    blurb: "Could not decide — this is not the same as a rejection.",
  },
  error: { label: "Error", blurb: "Our failure. Not charged against your quota." },
};

export const FAILURE_COPY: Record<string, string> = {
  below_threshold: "Below threshold",
  no_face_detected: "No face detected",
  multiple_faces: "More than one face",
  low_quality: "Quality too low",
  subject_not_enrolled: "Not enrolled",
  liveness_failed: "Liveness check failed",
  model_mismatch: "Model version mismatch",
};

export function failureLabel(code: string | null): string | null {
  if (!code) return null;
  return FAILURE_COPY[code] ?? code.replace(/_/g, " ");
}

// ── Threshold simulation ──────────────────────────────────────────────────────

export interface SimulatedFlip {
  id: string;
  subject_id: string | null;
  subject_external_id: string | null;
  similarity: number;
  original_decision: string;
  simulated_decision: string;
  confidence: string | null;
  created_at: string;
}

export interface SimilarityBucket {
  from: number;
  to: number;
  count: number;
}

export interface ThresholdSimulation {
  current_threshold: number;
  candidate_threshold: number;
  window_days: number;
  comparable: number;
  unchanged: number;
  original_verified: number;
  original_rejected: number;
  simulated_verified: number;
  simulated_rejected: number;
  newly_rejected: number;
  newly_accepted: number;
  acceptance_rate_before: number;
  acceptance_rate_after: number;
  examples: SimulatedFlip[];
  histogram: SimilarityBucket[];
}

/**
 * Replay recorded verifications against a candidate threshold.
 *
 * `placeholderData` keeps the previous result on screen while a new one loads,
 * so dragging the slider updates numbers in place instead of collapsing the
 * panel to skeletons on every step. The alternative flickers badly at the
 * ~200 ms this query takes.
 */
export function useThresholdSimulation(threshold: number, days = 30, enabled = true) {
  const orgId = useOrgId();
  return useQuery({
    queryKey: [...queryKeys.threshold(orgId), "simulate", threshold, days],
    queryFn: () =>
      api.get<ThresholdSimulation>(
        `/v1/console/threshold/simulate?threshold=${threshold}&days=${days}`,
      ),
    enabled: !!orgId && enabled,
    placeholderData: (previous) => previous,
    staleTime: 30_000,
  });
}
