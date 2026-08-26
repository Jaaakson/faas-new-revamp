/**
 * Release notes.
 *
 * A changelog signals the product is alive, and it is the cheapest possible
 * proof that development is real. Entries describe what shipped and what did
 * not — including the known gaps, which is what makes the rest credible.
 */

export interface ChangelogEntry {
  version: string;
  date: string;
  title: string;
  summary: string;
  changes: { type: "added" | "changed" | "fixed" | "known"; text: string }[];
}

export const changelog: ChangelogEntry[] = [
  {
    version: "0.2.0",
    date: "2026-07-31",
    title: "Public website",
    summary:
      "The marketing surface: landing page, features, use cases, pricing with a cost calculator, FAQ, contact, and the documentation shell.",
    changes: [
      { type: "added", text: "Landing page with live code samples and a real decision object" },
      { type: "added", text: "Four vertical use-case pages with threshold guidance per industry" },
      { type: "added", text: "Pricing page with an interactive volume-to-cost calculator" },
      { type: "added", text: "MDX documentation with build-time syntax highlighting" },
      { type: "added", text: "FAQ covering product, technical, security, and billing" },
      {
        type: "added",
        text: "Light and dark themes across every page, honoring system preference",
      },
      {
        type: "known",
        text: "The contact form validates but does not deliver yet — transactional email ships with authentication",
      },
    ],
  },
  {
    version: "0.1.0",
    date: "2026-07-31",
    title: "Foundation",
    summary:
      "The skeleton both applications are built on: configuration, logging, error handling, tenant-scoped data access, and CI.",
    changes: [
      {
        type: "added",
        text: "FastAPI application factory with typed configuration that fails fast",
      },
      {
        type: "added",
        text: "Structured JSON logging with request-ID tracing and secret redaction",
      },
      { type: "added", text: "Uniform error envelope with stable machine-readable codes" },
      {
        type: "added",
        text: "TenantScopedRepository — tenant isolation enforced structurally, not by convention",
      },
      { type: "added", text: "Cursor pagination keyed on the ULID primary key" },
      { type: "added", text: "Async SQLAlchemy with Alembic and the pgvector extension migration" },
      { type: "added", text: "Liveness and readiness probes with per-dependency reporting" },
      { type: "added", text: "Next.js 15 with the full OKLCH design token set" },
      { type: "added", text: "Docker Compose stack and a CI pipeline covering both applications" },
      {
        type: "fixed",
        text: "Cursor pagination returned duplicates when rows shared a timestamp — the keyset now rides the ULID",
      },
      {
        type: "known",
        text: "No domain schema yet; identity and biometrics tables land in the next two releases",
      },
    ],
  },
];
