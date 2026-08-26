/**
 * Pricing, mirroring docs/01-prd.md §7.
 *
 * Usage-based on the unit the customer values: a verification. Enrollments are
 * free — charging for onboarding suppresses the adoption that produces
 * verification volume.
 */

export interface Plan {
  id: string;
  name: string;
  price: number | null;
  priceLabel: string;
  cadence: string;
  description: string;
  verifications: number | null;
  overage: number | null;
  featured?: boolean;
  cta: { label: string; href: string };
  features: string[];
}

export const plans: Plan[] = [
  {
    id: "free",
    name: "Free",
    price: 0,
    priceLabel: "$0",
    cadence: "forever",
    description: "Enough to integrate, test, and demo the whole flow.",
    verifications: 1_000,
    overage: null,
    cta: { label: "Start free", href: "/register" },
    features: [
      "1,000 verifications / month",
      "500 subjects",
      "2 team members",
      "7-day log retention",
      "1 live key + test mode",
      "Community support",
    ],
  },
  {
    id: "startup",
    name: "Startup",
    price: 49,
    priceLabel: "$49",
    cadence: "per month",
    description: "For a product that has shipped and is growing.",
    verifications: 25_000,
    overage: 0.004,
    featured: true,
    cta: { label: "Start free trial", href: "/register?plan=startup" },
    features: [
      "25,000 verifications / month",
      "10,000 subjects",
      "5 team members",
      "30-day log retention",
      "Webhooks",
      "5 API keys",
      "Email support",
    ],
  },
  {
    id: "growth",
    name: "Growth",
    price: 199,
    priceLabel: "$199",
    cadence: "per month",
    description: "For teams running verification in a critical path.",
    verifications: 150_000,
    overage: 0.002,
    cta: { label: "Start free trial", href: "/register?plan=growth" },
    features: [
      "150,000 verifications / month",
      "Unlimited subjects",
      "20 team members",
      "90-day log retention",
      "Custom match threshold",
      "IP allowlisting",
      "99.5% uptime SLA",
      "Priority support",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: null,
    priceLabel: "Custom",
    cadence: "annual",
    description: "For regulated buyers with residency and procurement needs.",
    verifications: null,
    overage: null,
    cta: { label: "Contact sales", href: "/contact?topic=enterprise" },
    features: [
      "Custom volume",
      "Data residency",
      "On-premise deployment",
      "SSO / SAML",
      "1-year log retention",
      "99.9% uptime SLA",
      "Dedicated support channel",
    ],
  },
];

/** Rows for the full comparison table. `true`/`false` render as ✓/—. */
export const comparison: {
  group: string;
  rows: { label: string; values: (string | boolean)[] }[];
}[] = [
  {
    group: "Usage",
    rows: [
      {
        label: "Verifications / month",
        values: ["1,000", "25,000", "150,000", "Custom"],
      },
      { label: "Enrollments", values: ["Unlimited", "Unlimited", "Unlimited", "Unlimited"] },
      { label: "Subjects", values: ["500", "10,000", "Unlimited", "Unlimited"] },
      { label: "Overage per verification", values: ["—", "$0.004", "$0.002", "Custom"] },
      { label: "Team members", values: ["2", "5", "20", "Unlimited"] },
    ],
  },
  {
    group: "Features",
    rows: [
      { label: "Test mode", values: [true, true, true, true] },
      { label: "Duplicate face detection", values: [true, true, true, true] },
      { label: "Threshold presets", values: [true, true, true, true] },
      { label: "Custom threshold", values: [false, false, true, true] },
      { label: "Webhooks", values: [false, true, true, true] },
      { label: "API playground", values: [true, true, true, true] },
      { label: "Analytics", values: ["Basic", "Full", "Full", "Full"] },
    ],
  },
  {
    group: "Security & compliance",
    rows: [
      { label: "Audit log", values: [true, true, true, true] },
      { label: "Log retention", values: ["7 days", "30 days", "90 days", "1 year"] },
      { label: "Role-based access control", values: [true, true, true, true] },
      { label: "IP allowlisting", values: [false, false, true, true] },
      { label: "Data residency", values: [false, false, false, true] },
      { label: "SSO / SAML", values: [false, false, false, true] },
      { label: "DPA", values: [false, true, true, true] },
    ],
  },
  {
    group: "Support",
    rows: [
      { label: "Community", values: [true, true, true, true] },
      { label: "Email support", values: [false, true, true, true] },
      { label: "Priority support", values: [false, false, true, true] },
      { label: "Uptime SLA", values: ["—", "—", "99.5%", "99.9%"] },
    ],
  },
];

/**
 * Recommend a plan for an expected monthly volume, with the true cost including
 * overage. Exists because usage-based pricing creates purchase anxiety, and the
 * buyer should be able to resolve it without emailing sales.
 */
export function recommendPlan(volume: number): {
  plan: Plan;
  monthlyCost: number | null;
  overageUnits: number;
  overageCost: number;
} {
  const candidates = plans.filter((p) => p.verifications !== null);

  const fits = candidates.find((p) => volume <= (p.verifications ?? 0));
  if (fits) {
    return {
      plan: fits,
      monthlyCost: fits.price,
      overageUnits: 0,
      overageCost: 0,
    };
  }

  // Past the largest metered tier, Growth plus overage is still cheaper than
  // Enterprise for most volumes — recommend it honestly rather than pushing
  // everyone to "contact sales".
  const growth = candidates[candidates.length - 1]!;
  const overageUnits = volume - (growth.verifications ?? 0);
  const overageCost = overageUnits * (growth.overage ?? 0);

  // Past ~1M/month a negotiated contract genuinely beats metered overage.
  if (volume > 1_000_000) {
    return {
      plan: plans[plans.length - 1]!,
      monthlyCost: null,
      overageUnits: 0,
      overageCost: 0,
    };
  }

  return {
    plan: growth,
    monthlyCost: (growth.price ?? 0) + overageCost,
    overageUnits,
    overageCost,
  };
}
