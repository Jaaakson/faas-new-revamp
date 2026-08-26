## Summary

<!-- What does this change and why. One or two sentences. -->

Closes #

## Type

- [ ] `feat` — new capability
- [ ] `fix` — bug fix
- [ ] `refactor` — restructure, no behavior change
- [ ] `perf` — performance
- [ ] `docs` — documentation
- [ ] `test` — tests
- [ ] `chore` / `build` / `ci`

## Changes

<!-- Bullet the substantive changes. Skip the obvious ones. -->

-

## Screenshots / recording

<!-- Required for any UI change. Light and dark, mobile if the layout differs. -->

| Before | After |
| --- | --- |
|  |  |

## Testing

<!-- What you ran, and what a reviewer should run to convince themselves. -->

- [ ] Unit tests added or updated
- [ ] Integration tests cover the failure paths, not only the happy one
- [ ] Verified manually — steps:
- [ ] E2E updated if the critical flow changed

## Database

- [ ] No schema change
- [ ] Migration included, and `alembic downgrade` tested
- [ ] Expand-then-contract used for any rename or type change
- [ ] Indexes reviewed for the new query patterns

## Security & privacy

- [ ] Tenant-scoped queries go through `TenantScopedRepository`
- [ ] Authorization enforced server-side, not only in the UI
- [ ] No secrets, tokens, PII, embeddings, or image bytes in logs or responses
- [ ] Input validated with Pydantic / Zod
- [ ] Touches `face_templates` or biometric handling — **describe the impact below**

<!-- If the box above is checked, explain what changes and why it's safe. -->

## Frontend checklist

<!-- Delete if this is backend-only. -->

- [ ] Loading, empty, error, and success states all implemented
- [ ] Skeleton matches the final layout — no layout shift
- [ ] Keyboard-navigable with visible focus
- [ ] Contrast meets AA
- [ ] Responsive at 375 / 768 / 1440
- [ ] Respects `prefers-reduced-motion`

## API changes

- [ ] No public API change
- [ ] Additive only (backward compatible)
- [ ] **Breaking** — versioning and deprecation plan described below
- [ ] OpenAPI updated with `summary`, `description`, and an example
- [ ] Generated types regenerated (`contract` CI job passes)

## Docs

- [ ] No documentation impact
- [ ] `docs/` updated in this PR

<!-- A change to an API contract, the schema, or a security control must update
     the corresponding document here, not in a follow-up. -->

## Notes for the reviewer

<!-- Anything you're unsure about, alternatives you considered and rejected,
     or the part of the diff that deserves the most attention. -->
