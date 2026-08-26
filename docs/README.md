# Fvas — Blueprint

The design documentation for Fvas. This directory is the **specification**: implementation follows it, and a change to a contract, schema, or security control updates the relevant document in the same pull request.

---

## Read in order

| # | Document | Answers |
| --- | --- | --- |
| 01 | [Product Requirements](01-prd.md) | Who it's for, what we build, what we deliberately don't, how it's priced, what its honest limitations are |
| 02 | [Information Architecture](02-information-architecture.md) | Every surface and route; the navigation model; empty-state strategy |
| 03 | [User Flows & Wireframes](03-user-flows-wireframes.md) | End-to-end flows and screen-by-screen layout descriptions |
| 04 | [Design System](04-design-system.md) | Color tokens, type scale, spacing, components, motion, accessibility contract |
| 05 | [Technical Architecture](05-architecture.md) | System design, layering, tenancy, auth model, folder structure, decision log |
| 06 | [Database Design](06-database.md) | ERD, every table, indexes, query patterns, seed strategy |
| 07 | [REST API Design](07-api-design.md) | Both API surfaces, conventions, resources, errors, webhooks |
| 08 | [AI Workflow](08-ai-workflow.md) | The face pipeline, thresholds, evaluation, liveness limits, model licensing |
| 09 | [Security & Compliance](09-security.md) | Threat model, controls, RBAC matrix, biometric data posture |
| 10 | [Development Roadmap](10-roadmap.md) | Phases 0–9 with deliverables, dependencies, estimates, definition of done |
| 11 | [Deployment Strategy](11-deployment.md) | Environments, Docker, CI/CD, observability, scaling, cost |
| 12 | [Repository Standards](12-repository-standards.md) | Branching, commits, review, testing policy, releases |
| 13 | [Docker Setup Guide](13-docker-setup.md) | Running the stack locally, and what to do when it breaks |
| 14 | [Phase 0 Spike](14-phase-0-spike.md) | Measured latency and threshold calibration — the numbers behind §08 |

## Reading paths

**"Convince me this is a real product"** → [01](01-prd.md) → [03](03-user-flows-wireframes.md) → [10](10-roadmap.md)

**"Show me the engineering"** → [05](05-architecture.md) → [06](06-database.md) → [07](07-api-design.md) → [09](09-security.md)

**"I'm about to write code"** → [13](13-docker-setup.md) → [05](05-architecture.md) → [10](10-roadmap.md) → [12](12-repository-standards.md)

**"How does the face recognition actually work"** → [08](08-ai-workflow.md) → [14](14-phase-0-spike.md)

## The five decisions that shape everything else

1. **`users` and `subjects` are different tables.** Console operators and the end-users whose faces are enrolled have nothing in common — different scale, different auth, different lifecycle, different deletion obligations. Merging them breaks tenancy, privacy compliance, and scale simultaneously. → [06 §3](06-database.md#3-the-modelling-decision-that-matters-most)

2. **`FaceEngine` is an interface, not a call to InsightFace.** It buys a 2-minute CI pipeline, testability without model downloads, a licensing escape hatch, and the option to extract inference to its own service the day a metric justifies it. → [05 §7](05-architecture.md#7-the-face-engine)

3. **Tenant isolation is structural, not disciplined.** A base repository that injects the scope, generated cross-tenant tests over every endpoint, and Postgres RLS underneath. Code review is not an isolation mechanism. → [05 §5](05-architecture.md#5-multi-tenancy)

4. **The threshold is a measurement, not a constant.** It now comes off a real curve — 8,559 genuine and 500,000 impostor pairs — rather than an assertion, and is recorded per verification session. The per-slice demographic results remain outstanding and are named as such. → [14](14-phase-0-spike.md#3-threshold-calibration)

5. **The MVP does not ship certified liveness, and says so.** Quality gates and an optional active challenge raise the bar; they don't clear ISO 30107-3. The product is positioned as a step-up factor accordingly, and the interface for a real PAD model already exists. → [08 §5](08-ai-workflow.md#5-liveness--stated-limits)

## Diagrams

Mermaid diagrams render natively on GitHub. To edit them locally, use any Mermaid-capable editor — the source lives inline in each document, not in a separate binary file, so a diagram can never drift out of review.

---

← [Repository root](../README.md)
