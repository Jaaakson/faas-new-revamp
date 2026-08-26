"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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

export interface EnrollmentImageResult {
  index: number;
  accepted: boolean;
  quality_score: number;
  reason?: string | null;
  guidance?: string | null;
  checks: GateCheck[];
  bbox?: Record<string, number> | null;
}

export interface FaceProfile {
  id: string;
  version: number;
  status: string;
  template_count: number;
  avg_quality_score: number | null;
  model: { name: string; version: string };
  created_at: string;
  superseded_at: string | null;
  revoked_at: string | null;
}

export interface Subject {
  id: string;
  external_id: string;
  display_name: string | null;
  status: string;
  consent_reference: string | null;
  metadata: Record<string, unknown>;
  verification_count: number;
  enrolled_at: string | null;
  last_verified_at: string | null;
  created_at: string;
}

export interface SubjectDetail extends Subject {
  face_profile: FaceProfile | null;
  profile_history: FaceProfile[];
}

export interface EnrollmentResponse {
  id: string;
  status: string;
  subject_id: string | null;
  face_profile: FaceProfile | null;
  images: EnrollmentImageResult[];
  failure_reason: string | null;
  latency_ms: number;
  created_at: string;
}

export interface EnrollmentRow {
  id: string;
  subject_id: string | null;
  subject_external_id: string | null;
  status: string;
  failure_reason: string | null;
  image_count: number;
  accepted_count: number;
  duplicate_subject_id: string | null;
  latency_ms: number;
  source: string;
  created_at: string;
}

interface Paginated<T> {
  data: T[];
  pagination: { next_cursor: string | null; has_more: boolean; limit: number };
}

function useOrgId(): string {
  return useAuthStore((state) => state.organization?.id ?? "");
}

export function useSubject(subjectId: string) {
  const orgId = useOrgId();
  return useQuery({
    queryKey: queryKeys.subject(orgId, subjectId),
    queryFn: () => api.get<SubjectDetail>(`/v1/console/subjects/${subjectId}`),
    enabled: !!orgId && !!subjectId,
  });
}

export function useEnrollments(filters: { subjectId?: string; status?: string; limit?: number }) {
  const orgId = useOrgId();
  const params = new URLSearchParams();
  if (filters.subjectId) params.set("subject_id", filters.subjectId);
  if (filters.status) params.set("status", filters.status);
  params.set("limit", String(filters.limit ?? 20));

  return useQuery({
    queryKey: queryKeys.enrollments(orgId, filters),
    queryFn: () => api.get<Paginated<EnrollmentRow>>(`/v1/console/enrollments?${params}`),
    enabled: !!orgId,
    placeholderData: (previous) => previous,
  });
}

export function useCreateSubject() {
  const orgId = useOrgId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: {
      external_id: string;
      display_name?: string | null;
      consent_reference?: string | null;
    }) => api.post<Subject>("/v1/console/subjects", input),
    onSuccess: () => {
      // The list is a cursor-paginated read model; refetching is simpler and
      // more correct than trying to splice a new row into the right page.
      void queryClient.invalidateQueries({ queryKey: queryKeys.org(orgId) });
    },
  });
}

/**
 * Enrollment failures are *expected outcomes*, not exceptions.
 *
 * A 422 with per-frame reasons and a 409 duplicate are both answers the wizard
 * renders as UI. `retry: false` matters: replaying an enrollment would burn
 * quota and could create a second profile, and a duplicate face will still be a
 * duplicate on the second attempt.
 */
export function useEnroll() {
  const orgId = useOrgId();
  const queryClient = useQueryClient();

  return useMutation<
    EnrollmentResponse,
    ApiError,
    {
      subject_id: string;
      images: string[];
      options?: { check_duplicates?: boolean; replace_existing?: boolean; min_quality?: number };
    }
  >({
    mutationFn: (input) => api.post<EnrollmentResponse>("/v1/console/enrollments", input),
    retry: false,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.org(orgId) });
    },
  });
}

export function useDeleteSubject() {
  const orgId = useOrgId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (subjectId: string) =>
      api.delete<{ deleted: boolean; templates_destroyed: number }>(
        `/v1/console/subjects/${subjectId}`,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.org(orgId) });
    },
  });
}

export function useRevokeProfile() {
  const orgId = useOrgId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (subjectId: string) =>
      api.delete<{ revoked: boolean; templates_destroyed: number }>(
        `/v1/console/subjects/${subjectId}/face-profile`,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.org(orgId) });
    },
  });
}

/**
 * Copy for a server-side gate code.
 *
 * The server already returns `guidance`, and that is what the UI shows. This is
 * the fallback for a code a newer API version introduces before this build
 * knows about it — an unrecognised reason should still read as a sentence, not
 * as `pose_yaw`.
 */
export const GATE_LABELS: Record<string, string> = {
  min_face_size: "Face too small",
  sharpness: "Out of focus",
  brightness: "Lighting",
  contrast: "Contrast",
  pose_yaw: "Turned left or right",
  pose_pitch: "Tilted up or down",
  pose_roll: "Head tilted",
  detection_confidence: "Face not clearly visible",
  no_face_detected: "No face found",
  multiple_faces: "More than one face",
  low_quality: "Quality too low",
  duplicate_face: "Already enrolled",
};

export function gateLabel(code: string): string {
  return GATE_LABELS[code] ?? code.replace(/_/g, " ");
}
