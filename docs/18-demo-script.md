# 18 — Demo script

Three minutes, no code editor, no terminal gymnastics. Written to be *read
aloud* while clicking.

The through-line: **this is not a face-recognition toy, it is an authentication
API with an audit trail.** Every beat below exists to make one of those words
land.

---

## Before you start

```bash
make up
docker compose exec api alembic upgrade head
docker compose exec api python -m app.cli seed
```

Open two tabs: the console at `http://localhost:3000`, and the docs at
`http://localhost:3000/docs/quickstart`.

Sign in as `owner@acme.example.com` / `Password123!demo`.

> **Timing.** The API half of this script was measured end to end at **0.8
> seconds** of server time — login, key creation, subject creation, a 3-frame
> enrollment, and three verifications. The three minutes is talking and
> clicking, not waiting. Numbers per step are at the bottom.

---

## 0:00 — What it is (20s)

> "Fvas is face authentication as an API. A customer enrolls one of their users
> once, then asks us a single question — *is this the same person?* — and gets
> an answer in under a second, with an audit record for every decision.
>
> It is deliberately not a face-recognition toolkit. There is exactly one
> question it answers."

**Show:** the dashboard. Point at verifications, success rate, p95 latency.

---

## 0:20 — Enroll from the browser (50s)

**Do:** Subjects → pick one → *Enroll face*.

> "A subject is one of the customer's end users, identified by *their* ID, not
> ours — nothing in their database has to change.
>
> The capture UI checks lighting, focus and steadiness locally, several times a
> second, and auto-captures when they hold. That is not the security check — the
> server does that — it is so a user learns their room is too dark in
> milliseconds instead of after a round trip."

**Show:** the three quality meters moving as you tilt the camera.

> "Three shots at slightly different angles. Templates covering a small range of
> poses are what make matching robust to how someone happens to stand."

**Do:** complete it. Land on the per-frame quality panel.

> "Per-frame results come back on success too, so an integrator can see *which*
> frame was weak instead of guessing."

---

## 1:10 — Verify, three ways (50s)

**Do:** `/dashboard/verify`. Capture yourself against the subject you enrolled.

> "Verified. Similarity 0.99, confidence *high* — that band is relative to the
> threshold, so a customer's risk engine can demand a second factor on a
> marginal match."

**Do:** verify against a *different* subject.

> "Rejected. A real face, but not this person."

**Do:** cover the lens, verify again.

> "**Inconclusive** — and this is the part most systems get wrong. We did not
> say 'you are an impostor'. We said 'I could not decide, the frame is unusable'.
>
> Collapsing those two would tell someone in a dark room that they are a fraud,
> and it would fill the customer's fraud metrics with lighting problems."

---

## 2:00 — It is an API, not a dashboard (40s)

**Do:** API keys → *New key* → create.

> "The secret is shown once. We store a hash, so this dialog will not let you
> close it until you have copied the key."

**Do:** try to dismiss it. It refuses. Copy it.

**Do:** Docs → Quickstart. Switch the code samples to Go, then Python.

> "Same three calls in four languages, and the language choice follows you
> across every example on the site."

**Do:** back to API keys → *Revoke*.

> "Revocation takes effect on the next request. No cache, no grace period."

---

## 2:40 — The part buyers actually ask about (20s)

**Do:** Logs → Audit.

> "Every mutating action, append-only — the application's database role has no
> UPDATE or DELETE on this table.
>
> Deleting a subject destroys the biometric templates physically; there is no
> soft delete for biometric data. And the threshold that produced a decision is
> frozen onto that record, so changing it next month cannot rewrite what
> happened this month."

**Close:**

> "Enrollment, verification, an audit trail, and an honest answer when it cannot
> decide. What it deliberately does not have is certified liveness — that is
> stated in the docs, the PRD and the model card, because it decides where this
> belongs in someone's security design."

---

## If you have another minute

- **Tenant isolation** — the generated suite drives every id-addressed route across a tenant boundary, both auth planes, zero skips. Postgres RLS sits under it: with no tenant bound, an unfiltered query returns **zero rows**.
- **The model card** ([16](16-model-card.md)) — measured FAR/FRR, and a longer section on what was *not* measured.
- **The restore drill** ([17 §4](17-deployment-runbook.md)) — the database was destroyed and recovered, with a checksum comparison.

---

## Measured step timings

Server time only, against the local stack with `FACE_ENGINE=fake`:

| Step | Time |
| --- | ---: |
| Log in | 224 ms |
| Create an API key | 173 ms |
| Create a subject | 109 ms |
| Enroll 3 frames | 87 ms |
| Verify — same person | 37 ms |
| Verify — different person | 65 ms |
| Verify — unusable frame | 67 ms |
| **Total** | **761 ms** |

With the real engine, add roughly the Phase 0 figure — p95 331 ms per
inference — to each verification.

---

## What not to claim

- Do not say "liveness detection" without "heuristic, not certified".
- Do not quote accuracy without saying **LFW**. The per-slice numbers do not exist yet.
- Do not demo on a phone screen held up to the camera and call it a PAD test. It will probably be caught, and that is not the same as it being reliable.
