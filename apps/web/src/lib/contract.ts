/**
 * Compile-time conformance between the hand-written client types and the
 * backend's generated schema.
 *
 * The feature modules declare their own interfaces because they read better at
 * the call site than `components["schemas"]["VerificationResponse"]` and because
 * a few of them narrow a `string` into a union the schema cannot express. The
 * cost of that ergonomics is drift: a backend field that changes type would go
 * unnoticed until it broke at runtime, in front of a user.
 *
 * This file removes that cost. Each assertion below fails to compile if the
 * hand-written shape stops being assignable to the generated one, which turns
 * "the backend changed and the frontend did not" into a build error — the CI
 * gate the roadmap asks for.
 *
 * It emits nothing. Every export is a type, so the bundle is unaffected.
 *
 * When one of these breaks: run `make openapi`, read the diff in
 * `packages/shared/src/api.d.ts`, and update the corresponding interface. Do not
 * silence the assertion — it is the only thing standing between a schema change
 * and a production bug.
 */

import type { components } from "@fvas/shared";

import type {
  EnrollmentResponse,
  FaceProfile,
  Subject,
  SubjectDetail,
} from "@/features/biometrics/api";
import type {
  ThresholdInfo,
  VerificationDetail,
  VerificationResult,
} from "@/features/verification/api";

type Schema = components["schemas"];

/**
 * `Extends<A, B>` resolves only when `A` is assignable to `B`.
 *
 * Deliberately one-directional. The client may legitimately be *narrower* than
 * the schema — a `decision: "verified" | "rejected" | …` union is more precise
 * than the schema's `string`, and that is an improvement, not drift. What must
 * never happen is the client claiming a field the backend does not send, or
 * claiming a type the backend cannot produce.
 */
type Extends<A extends B, B> = A;

// ── Biometrics ────────────────────────────────────────────────────────────────

export type SubjectConforms = Extends<Subject, Schema["SubjectResponse"]>;
export type SubjectDetailConforms = Extends<SubjectDetail, Schema["SubjectDetail"]>;
export type FaceProfileConforms = Extends<FaceProfile, Schema["FaceProfileResponse"]>;
export type EnrollmentConforms = Extends<EnrollmentResponse, Schema["EnrollmentResponse"]>;

// ── Verification ──────────────────────────────────────────────────────────────

export type VerificationConforms = Extends<VerificationResult, Schema["VerificationResponse"]>;
export type VerificationDetailConforms = Extends<VerificationDetail, Schema["VerificationDetail"]>;
export type ThresholdConforms = Extends<ThresholdInfo, Schema["ThresholdInfo"]>;
