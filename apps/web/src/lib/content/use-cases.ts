/**
 * Vertical use cases, matching the ICP table in docs/01-prd.md §3.
 *
 * Each one names a concrete trigger and a concrete integration point rather
 * than a generic benefit — a prospect should recognize their own problem in the
 * first sentence.
 */

export interface UseCase {
  slug: string;
  name: string;
  icon: "landmark" | "stethoscope" | "truck" | "users";
  headline: string;
  summary: string;
  trigger: string;
  integrationPoint: string;
  outcomes: string[];
  threshold: { preset: string; value: string; reason: string };
  considerations: string[];
}

export const useCases: UseCase[] = [
  {
    slug: "digital-lending",
    name: "Digital lending & fintech",
    icon: "landmark",
    headline: "Verify the borrower before the money moves.",
    summary:
      "Account takeover and identity fraud concentrate at the moment of disbursement. A password proves someone has credentials; a face proves who is holding the phone.",
    trigger: "Fraudulent disbursement and account takeover on high-value transfers",
    integrationPoint:
      "Step-up verification between loan approval and fund release, or before any transfer above your risk threshold.",
    outcomes: [
      "Face verification as a second factor on disbursement, not on every login",
      "Confidence bands feed your existing risk engine instead of replacing it",
      "Audit log evidences who was verified, when, and against which template",
      "Duplicate detection catches one person enrolling under two borrower identities",
    ],
    threshold: {
      preset: "Strict",
      value: "0.45",
      reason:
        "The cost of a false accept is a fraudulent disbursement; the cost of a false reject is one retry. The asymmetry justifies the stricter setting.",
    },
    considerations: [
      "Fvas is a factor, not a KYC suite — pair it with document verification at onboarding",
      "Not certified PAD, so keep it inside a session you already authenticated",
    ],
  },
  {
    slug: "healthcare",
    name: "Healthcare platforms",
    icon: "stethoscope",
    headline: "Confirm the clinician at the terminal is the licensed clinician.",
    summary:
      "Shared workstations and shared passwords are endemic in clinical settings. Access to patient records needs an identity check that cannot be handed to a colleague.",
    trigger: "Credential sharing on shared terminals; access-control audit findings",
    integrationPoint:
      "Verification when a clinician opens a patient record from a shared device, or when signing a prescription.",
    outcomes: [
      "Non-transferable factor on shared workstations",
      "Every record access carries a verification session ID",
      "Templates only — no photographs retained in a clinical system",
      "Exportable audit trail for access-control reviews",
    ],
    threshold: {
      preset: "Balanced",
      value: "0.38",
      reason:
        "Clinicians verify many times a shift. A stricter threshold trades a rare false accept for frequent retries that push staff back toward shared logins.",
    },
    considerations: [
      "Clinical lighting varies widely — expect to tune after reviewing the hour-of-day success rate",
      "Consent and retention must be agreed with your compliance function before rollout",
    ],
  },
  {
    slug: "logistics",
    name: "Logistics & field operations",
    icon: "truck",
    headline: "Know which driver actually showed up.",
    summary:
      "Proxy drivers and handover fraud are hard to police with paperwork. A verification at handover ties a specific person to a specific consignment.",
    trigger: "Proxy drivers, handover disputes, cargo loss investigations",
    integrationPoint:
      "Verification in your driver app at shift start and at each custody handover.",
    outcomes: [
      "Identity tied to each custody event, not just a scanned barcode",
      "Works from a mid-range phone camera on mobile data",
      "Failure reasons distinguish a wrong person from a bad photo",
      "Evidence trail for loss and dispute investigations",
    ],
    threshold: {
      preset: "Lenient to Balanced",
      value: "0.32 – 0.38",
      reason:
        "Field conditions are hostile: night shifts, glare, dust, motion. Start lenient, watch the failure-reason breakdown, and tighten once capture quality is understood.",
    },
    considerations: [
      "Capture quality dominates outcomes here — invest in the in-app capture guidance",
      "Expect a visible night-shift dip in the hour-of-day heatmap; it is usually lighting, not fraud",
    ],
  },
  {
    slug: "hr-tech",
    name: "HR-tech & workforce platforms",
    icon: "users",
    headline: "Give your customers a face factor without building one.",
    summary:
      "If you sell workforce software, your customers keep asking for biometric check-in. Building it means hiring ML engineers and owning a biometric compliance story.",
    trigger: "Ghost employees and proxy check-in reported by your own customers",
    integrationPoint:
      "Embed verification in your check-in flow; one Fvas organization per tenant keeps their data isolated.",
    outcomes: [
      "Ship a biometric feature in weeks instead of quarters",
      "Per-tenant isolation maps onto your own multi-tenant model",
      "Per-verification pricing you can pass through or absorb",
      "The compliance story is documented rather than improvised",
    ],
    threshold: {
      preset: "Balanced",
      value: "0.38",
      reason:
        "Check-in happens daily and cooperatively. Balanced keeps false rejections low enough that staff do not route around the system.",
    },
    considerations: [
      "Attendance is a use of Fvas, not what Fvas is — you own the shift and payroll logic",
      "Your customers are the data controllers; make consent capture explicit in your own flow",
    ],
  },
];

export function getUseCase(slug: string): UseCase | undefined {
  return useCases.find((useCase) => useCase.slug === slug);
}
