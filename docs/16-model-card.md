# 16 — Model card

Published because a face-authentication product that will not say what its
error rates are, and on what data, is asking to be trusted on vibes.

Everything below is either a measurement with its conditions stated, or an
explicit "not measured". There is no third category.

---

## 1. What the system is

| | |
| --- | --- |
| Task | **1:1 verification** — "is this the person this profile belongs to?" |
| Not the task | 1:N identification, demographic inference, emotion, age, or any other attribute |
| Detection | SCRFD-10GF (`det_10g.onnx`), 320×320 input |
| Embedding | ArcFace R50 (`w600k_r50.onnx`), 512-d, L2-normalised |
| Similarity | Cosine, computed as a dot product on normalised vectors |
| Decision | `similarity ≥ threshold` → `verified`, else `rejected`; undecidable inputs → `inconclusive` |
| Runtime | ONNX Runtime, CPU, `intra_op_num_threads=2` |
| Source | InsightFace `buffalo_l` pack, pretrained. **Nothing here was trained by us.** |

The models are used as published. No fine-tuning, no distillation, no
modification of the preprocessing beyond matching the published alignment.

---

## 2. Measured performance

**Dataset:** Labeled Faces in the Wild (LFW).
**Protocol:** 8,559 genuine pairs, 500,000 impostor pairs, sampled by identity.
**Hardware:** the target CPU profile from [14 — Phase 0 spike](14-phase-0-spike.md).

### Operating points

| Preset | Threshold | FAR | FRR | TAR @ FAR=10⁻⁴ |
| --- | ---: | ---: | ---: | ---: |
| Lenient | 0.32 | 1.0×10⁻⁵ | 2.73% | — |
| **Balanced (shipped default)** | **0.38** | **8.0×10⁻⁶** | **3.06%** | **97.36%** |
| Strict | 0.45 | 8.0×10⁻⁶ \* | 4.21% | — |

\* **Identical to Balanced, and that is a limit of the measurement, not a
property of the threshold.** Beyond roughly 0.35 the impostor tail falls below
what 500,000 pairs can resolve — the observed count reaches zero, and zero
observed failures is not the same as a lower failure rate. Strict remains
available as defence in depth against a population harder than LFW, but its
additional benefit here is **unquantified**.

### Why 0.38 rather than the FAR=10⁻⁴ point

The threshold that lands exactly on FAR = 10⁻⁴ measures **0.260** (FRR 2.64%).
The shipped default is 0.380 anyway. That buys a false-accept rate roughly
twelve times stricter than target for **+0.42 points of FRR** — and LFW is
easier than production, so a threshold tuned precisely to its 10⁻⁴ point would
drift toward false accepts on real captures.

The FAR/FRR curve is at
[`docs/assets/phase-0-far-frr-curve.png`](assets/phase-0-far-frr-curve.png).

---

## 3. What was not measured

This section is longer than the previous one, deliberately.

- **No per-slice results.** LFW is demographically skewed — predominantly light-skinned, male, and Western — and cannot support meaningful accuracy figures broken down by skin tone, age, or gender presentation. [01 — PRD §4](01-prd.md) commits to publishing per-slice results; **that commitment is outstanding and cannot be met from this dataset.** Anyone deploying against a population unlike LFW should treat the figures above as an upper bound.
- **No production-population validation.** Every number here comes from a curated public benchmark: frontal, well-lit, mostly cooperative. Field captures are none of those things.
- **Quality-gate thresholds are estimates, not measurements.** Face size, sharpness, brightness, contrast and pose limits were reasoned about, not calibrated. They are the next thing to measure.
- **Head pose is approximated**, not solved. Yaw and pitch come from five-landmark geometry, monotonic in the true angle but uncalibrated in degrees. Roll is exact.
- **Presentation-attack detection is heuristic and uncertified.** See §5 below.
- **No adversarial testing.** No attempt was made to construct inputs that mislead the detector or the embedder.
- **No twin or close-relative evaluation.** LFW contains no systematic set of these, and they are the hardest genuine-impostor case in practice.

---

## 4. Where the errors land

| Outcome | Meaning | Who it hurts |
| --- | --- | --- |
| **False reject** (FRR 3.06%) | A legitimate person is refused | The user, immediately and visibly. About 1 in 33 attempts at the default threshold |
| **False accept** (FAR 8×10⁻⁶) | The wrong person is admitted | The customer, silently. Roughly 1 in 125,000 impostor attempts |
| **Inconclusive** | No decision was possible | Recoverable — the user retakes, with specific guidance |

The three-way outcome exists so the third row is not silently counted as the
first. Collapsing `inconclusive` into `rejected` would tell a person in a dark
room that they are an impostor, and would fill the customer's fraud metrics with
lighting problems.

---

## 5. Presentation attacks — stated limits

**This is not certified PAD.** The shipped detector is three cheap heuristics:
spectral peak detection for screen moiré, specular-highlight clustering, and
micro-texture density.

| Stops | Does not stop |
| --- | --- |
| A face on a phone screen | A good screen at the right angle |
| A low-quality print | A high-quality print |
| | A prepared video, a deepfake, a mask |

Measured on synthetic samples during development, not on an attack corpus.
Evaluation against ISO/IEC 30107-3 categories has **not** been done.

**Consequence for deployment:** appropriate as a step-up factor where the
attacker also needs the account, the device and the session. **Not** appropriate
as the sole control for unsupervised remote onboarding against a motivated
adversary. That is a scoping statement, not a disclaimer.

---

## 6. Data handling

| | |
| --- | --- |
| Raw images | **Not stored.** Held in memory for the duration of the request, then discarded |
| Templates | 512 floats. Not reversible to an image, but still biometric data under GDPR Art. 9 |
| Deletion | Physical. `face_templates` has no `deleted_at` — a soft-deleted template is retained biometric data |
| Model versioning | Recorded per profile, so an upgrade produces a detectable `model_mismatch` rather than a silent accuracy collapse |

---

## 7. Licensing

The `buffalo_l` weights are published by InsightFace **for non-commercial
research use**. That is a blocker for revenue, tracked as a P0 post-MVP item in
[10 — Roadmap](10-roadmap.md). The `FaceEngine` protocol exists partly so that
swapping to a commercially licensed model is one adapter, not a rewrite.

---

## 8. Reproducing these numbers

```bash
cd spikes/phase-0-face-pipeline
docker build -t fvas-spike:phase0 .
docker run --rm -v "$PWD/output:/output" fvas-spike:phase0 python calibrate_threshold.py
```

Re-run this before changing any threshold. A number in this document that is not
backed by a run is a number that should not be in this document.
