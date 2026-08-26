"""The CPU half of enrollment: detect, gate, embed.

Deliberately pure. No session, no settings lookup, no I/O — the inputs are
decoded frames and the output is a value object. That has three consequences
that all matter:

* it can be handed to a worker thread **once** for the whole batch rather than
  once per frame, so a five-shot enrollment costs one context switch instead of
  fifteen;
* it can be tested without a database or an HTTP client;
* the service layer above it stays readable as a sequence of decisions, with all
  the numpy in here.

Order is not arbitrary. Detection is cheapest, gating is nearly free once a face
is located, and embedding is by far the most expensive stage
(docs/14-phase-0-spike.md §2 measured ~121 ms detect vs ~181 ms embed). Gating
before embedding means a blurred frame costs a detection, not a full pipeline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from app.modules.biometrics.engine.base import (
    DetectedFace,
    Embedding,
    FaceEngine,
    QualityReport,
)
from app.modules.biometrics.engine.quality import GATE_GUIDANCE

# Reason codes. Machine-readable, surfaced verbatim in the API envelope so an
# integrator can branch on them, and stored on the attempt row for analytics.
NO_FACE_DETECTED = "no_face_detected"
MULTIPLE_FACES = "multiple_faces"
LOW_QUALITY = "low_quality"


@dataclass(frozen=True, slots=True)
class FrameOutcome:
    """What happened to one submitted frame."""

    index: int
    accepted: bool
    quality_score: float
    reason: str | None = None
    guidance: str | None = None
    report: QualityReport | None = None
    face: DetectedFace | None = None
    embedding: Embedding | None = None

    def as_dict(self) -> dict[str, object]:
        body: dict[str, object] = {
            "index": self.index,
            "accepted": self.accepted,
            "quality_score": round(self.quality_score, 3),
        }
        if self.reason:
            body["reason"] = self.reason
        if self.guidance:
            body["guidance"] = self.guidance
        if self.report is not None:
            body["checks"] = [gate.as_dict() for gate in self.report.gates]
        if self.face is not None:
            body["bbox"] = self.face.bbox.as_dict()
        return body


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    frames: list[FrameOutcome]
    detect_ms: int
    embed_ms: int

    @property
    def accepted(self) -> list[FrameOutcome]:
        return [frame for frame in self.frames if frame.accepted]

    @property
    def dominant_reason(self) -> str | None:
        """The reason to report when nothing was accepted.

        The most common failure across frames, not the first — telling a user
        "no face detected" because frame 0 was a wall, when the other four were
        merely blurred, sends them to fix the wrong thing.
        """
        reasons = [frame.reason for frame in self.frames if frame.reason]
        if not reasons:
            return None
        return max(set(reasons), key=reasons.count)


def process_frames(
    engine: FaceEngine,
    frames: list[NDArray[np.uint8]],
    *,
    strict: bool,
    min_quality: float | None = None,
) -> BatchOutcome:
    """Run every frame through the pipeline and report all outcomes.

    Every frame is processed even after one fails. A capture UI needs to coach
    the user on all the problems at once; stopping at the first failure turns
    one retake into three.
    """
    outcomes: list[FrameOutcome] = []
    detect_ns = 0
    embed_ns = 0

    for index, frame in enumerate(frames):
        started = time.perf_counter_ns()
        faces = engine.detect(frame)
        detect_ns += time.perf_counter_ns() - started

        if not faces:
            outcomes.append(
                FrameOutcome(
                    index=index,
                    accepted=False,
                    quality_score=0.0,
                    reason=NO_FACE_DETECTED,
                    guidance="No face was found. Center your face in the frame.",
                )
            )
            continue

        if len(faces) > 1:
            # Refusing is the safe answer, not picking the largest. Enrolling
            # the wrong person from a frame with a bystander produces a profile
            # that silently authenticates the wrong human forever.
            outcomes.append(
                FrameOutcome(
                    index=index,
                    accepted=False,
                    quality_score=0.0,
                    reason=MULTIPLE_FACES,
                    guidance="More than one face is visible. Capture one person at a time.",
                    face=faces[0],
                )
            )
            continue

        face = faces[0]
        report = engine.assess_quality(frame, face, strict=strict)
        score = report.score

        failure = report.first_failure
        if failure is not None:
            outcomes.append(
                FrameOutcome(
                    index=index,
                    accepted=False,
                    quality_score=score,
                    reason=LOW_QUALITY,
                    guidance=GATE_GUIDANCE.get(failure.name, "Retake the photo."),
                    report=report,
                    face=face,
                )
            )
            continue

        # A caller-supplied floor on top of the gates. The gates say "usable";
        # this says "usable enough for what I am about to trust it with", which
        # is the caller's risk decision, not ours.
        if min_quality is not None and score < min_quality:
            outcomes.append(
                FrameOutcome(
                    index=index,
                    accepted=False,
                    quality_score=score,
                    reason=LOW_QUALITY,
                    guidance=(
                        f"Quality {score:.2f} is below the requested minimum {min_quality:.2f}."
                    ),
                    report=report,
                    face=face,
                )
            )
            continue

        started = time.perf_counter_ns()
        embedding = engine.embed(frame, face)
        embed_ns += time.perf_counter_ns() - started

        outcomes.append(
            FrameOutcome(
                index=index,
                accepted=True,
                quality_score=score,
                report=report,
                face=face,
                embedding=embedding,
            )
        )

    return BatchOutcome(
        frames=outcomes,
        detect_ms=detect_ns // 1_000_000,
        embed_ms=embed_ns // 1_000_000,
    )
