/**
 * FAQ content, grouped.
 *
 * Answers are deliberately direct about limitations — the liveness and bias
 * entries especially. A prospect who finds out during a security review what
 * the FAQ concealed does not come back.
 */

export interface FaqItem {
  question: string;
  answer: string;
}

export interface FaqGroup {
  title: string;
  items: FaqItem[];
}

export const faqGroups: FaqGroup[] = [
  {
    title: "Product",
    items: [
      {
        question: "What exactly does Fvas do?",
        answer:
          "It answers one question with an audit trail: is the person in front of this camera the same person who enrolled as this subject? You enroll a face once, then verify against it as often as you need. Fvas is an authentication factor you add to your existing login — not a replacement identity provider.",
      },
      {
        question: "Is this an attendance or face-recognition app?",
        answer:
          "No. Attendance products are built around shifts, schedules, and payroll. General face recognition searches a crowd for anyone. Fvas does 1:1 verification against a subject you name in the request, which is a different problem with different security properties.",
      },
      {
        question: "How is this different from a KYC vendor?",
        answer:
          "KYC products are priced and shaped for one-time onboarding: document capture, liveness, watchlist screening, per-onboarding pricing. Using one for daily re-authentication is economically absurd. Fvas is priced per verification because verification is the repeated action.",
      },
      {
        question: "Do I need machine-learning expertise to use it?",
        answer:
          "No. You send an image and a subject ID over HTTPS and get a decision back. Threshold selection is exposed as three presets, and every response includes the score and the threshold it was compared against so you can audit any decision.",
      },
    ],
  },
  {
    title: "Technical",
    items: [
      {
        question: "How fast is a verification?",
        answer:
          "Typically 200–350 ms server-side, with a p95 target under 800 ms. Every response includes a timing breakdown — detection, embedding, and matching — so the number is continuously checkable rather than a benchmark in a README.",
      },
      {
        question: "How accurate is it?",
        answer:
          "The target is a true accept rate of at least 97% at a false accept rate of 1e-4, measured on a validation set rather than assumed. We publish the FAR/FRR curve and per-demographic results in the model card. We do not report a single 'accuracy' number, because it hides which of the two errors you are buying.",
      },
      {
        question: "What images work best?",
        answer:
          "A single face, well lit, roughly facing the camera, at least 112 pixels between the eyes. Quality gates run before matching, so a bad capture returns an inconclusive result with a specific reason — 'too dark', 'face too small' — rather than a wrong decision.",
      },
      {
        question: "What happens if the image is unusable?",
        answer:
          "You get `inconclusive`, not `rejected`. That distinction matters: telling a user 'you are not who you say you are' when the real problem is a dark room is both wrong and corrupting to your fraud metrics.",
      },
      {
        question: "Can I self-host it?",
        answer:
          "On-premise deployment is available on Enterprise. The architecture is a single container plus PostgreSQL, so it is deliberately deployable inside your own network.",
      },
    ],
  },
  {
    title: "Security & privacy",
    items: [
      {
        question: "Does Fvas store photographs of my users?",
        answer:
          "No, not by default. Images are converted to a 512-dimension mathematical template and then discarded. Retention is opt-in per organization, off by default, and surfaced in settings with a plain-language warning.",
      },
      {
        question: "Does it detect photos, screens, or deepfakes?",
        answer:
          "Partially, and we would rather say so than imply otherwise. The current release ships quality gates, screen-replay and texture heuristics, and an optional active challenge. It is not certified presentation-attack detection under ISO 30107-3. Fvas is appropriate as a step-up factor within a session you already control; it is not appropriate as the sole control for unsupervised remote onboarding against a motivated attacker.",
      },
      {
        question: "Is face recognition biased?",
        answer:
          "Differential performance across demographic groups is a real, documented property of face recognition, and pretending otherwise would be dishonest. We calibrate on a demographically stratified validation set, publish per-slice false rejection rates, and let you tune the threshold. Measuring and publishing it is the responsible position; omitting the measurement is not.",
      },
      {
        question: "How do I delete a user's biometric data?",
        answer:
          "Call DELETE on the subject. Template rows are physically deleted, not flagged — a soft-deleted biometric template is still retained biometric data. The deletion is recorded in the audit log so you can evidence it.",
      },
      {
        question: "Who is the data controller?",
        answer:
          "You are. Fvas is the processor. You capture consent and pass a reference to it on the subject record; we process on your instruction, never train on your data, and never share it. A DPA is available from the Startup plan up.",
      },
    ],
  },
  {
    title: "Billing",
    items: [
      {
        question: "What counts as a billable verification?",
        answer:
          "A completed verification that produced a decision — verified, rejected, or inconclusive. Pipeline errors on our side are not billed. Enrollments are always free.",
      },
      {
        question: "What happens when I hit my quota?",
        answer:
          "Free plans stop at the limit with a 429. Paid plans keep serving and bill overage, because a billing event must never break a customer's login flow.",
      },
      {
        question: "Do test-mode requests count?",
        answer:
          "No. Test keys write to the same schema with an environment flag, so test data appears in your dashboard behind a banner but never touches billing or production analytics.",
      },
      {
        question: "Can I change plans mid-cycle?",
        answer:
          "Yes, in either direction. Upgrades take effect immediately and are prorated; downgrades apply at the next billing period so you keep what you have paid for.",
      },
    ],
  },
];

/** Flattened, for the landing page's short FAQ and for JSON-LD. */
export const topFaqs: FaqItem[] = [
  faqGroups[0]!.items[0]!,
  faqGroups[0]!.items[2]!,
  faqGroups[2]!.items[0]!,
  faqGroups[2]!.items[1]!,
  faqGroups[1]!.items[0]!,
  faqGroups[3]!.items[1]!,
];
