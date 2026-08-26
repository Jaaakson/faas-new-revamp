"""The face engine interface.

The single most important abstraction in the codebase
(docs/05-architecture.md §7). Everything above it — enrollment, verification,
quality gating — depends on this protocol and never on InsightFace.

That buys four things, all of them already cashed in:

* the test suite runs in seconds with no model download,
* the Phase 0 spike could measure alternatives without touching the product,
* a commercially licensed model is a one-adapter swap
  (docs/08-ai-workflow.md §9),
* inference can move to its own service when a metric justifies it, rather than
  when someone guesses it should.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

Embedding = NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    def as_dict(self) -> dict[str, float]:
        return {
            "x1": round(self.x1, 2),
            "y1": round(self.y1, 2),
            "x2": round(self.x2, 2),
            "y2": round(self.y2, 2),
            "score": round(self.score, 4),
        }


@dataclass(frozen=True, slots=True)
class Pose:
    yaw: float
    pitch: float
    roll: float


@dataclass(frozen=True, slots=True)
class DetectedFace:
    """One detected face and the geometry needed to align it."""

    bbox: BoundingBox
    # Five points: both eyes, nose tip, both mouth corners. The similarity
    # transform to ArcFace's canonical layout is computed from these — matching
    # training-time preprocessing is not optional (docs/08-ai-workflow.md §1).
    landmarks: NDArray[np.float32]
    pose: Pose
    # Distance between the eyes, in pixels of the source frame. The size gate
    # measures this rather than bounding-box area, because a box scales with
    # hair and chin while the inter-ocular distance tracks usable detail.
    inter_ocular_px: float


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    passed: bool
    score: float
    value: float
    threshold: float

    def as_dict(self) -> dict[str, object]:
        return {
            "check": self.name,
            "passed": self.passed,
            "score": round(self.score, 3),
            "value": round(self.value, 3),
            "required": round(self.threshold, 3),
        }


@dataclass
class QualityReport:
    """The outcome of every gate, not just the first failure.

    Returning all of them lets a capture UI coach the user once instead of
    round-tripping per problem.
    """

    gates: list[GateResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(gate.passed for gate in self.gates)

    @property
    def score(self) -> float:
        """Mean of the per-gate scores — what the console displays."""
        if not self.gates:
            return 0.0
        return sum(gate.score for gate in self.gates) / len(self.gates)

    @property
    def first_failure(self) -> GateResult | None:
        return next((gate for gate in self.gates if not gate.passed), None)

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "score": round(self.score, 3),
            "checks": [gate.as_dict() for gate in self.gates],
        }


@dataclass(frozen=True, slots=True)
class ModelInfo:
    name: str
    version: str
    embedding_dim: int


@runtime_checkable
class FaceEngine(Protocol):
    """Detect, align, embed, compare.

    Implementations are synchronous and CPU-bound. Callers are responsible for
    keeping them off the event loop — see `run_in_threadpool` at the call site.
    """

    @property
    def model(self) -> ModelInfo: ...

    def detect(self, image: NDArray[np.uint8]) -> list[DetectedFace]:
        """Every face in the frame, largest first."""
        ...

    def assess_quality(
        self, image: NDArray[np.uint8], face: DetectedFace, *, strict: bool
    ) -> QualityReport:
        """Run the gates.

        `strict` is used for enrollment. Someone enrolling is cooperative and
        can retry; someone authenticating at 11pm in a badly lit warehouse
        cannot. Applying enrollment-grade strictness at verification produces a
        system that is technically accurate and practically unusable
        (docs/08-ai-workflow.md §2).
        """
        ...

    def embed(self, image: NDArray[np.uint8], face: DetectedFace) -> Embedding:
        """Align to 112x112 and return an L2-normalised 512-d embedding."""
        ...


def cosine_similarity(a: Embedding, b: Embedding) -> float:
    """Both inputs are L2-normalised, so this is a dot product.

    Kept as a module function rather than an engine method: it is pure
    arithmetic on the engine's *output* and must behave identically no matter
    which engine produced it.
    """
    return float(np.dot(a.ravel(), b.ravel()))


def best_match(probe: Embedding, templates: list[Embedding]) -> tuple[int, float]:
    """Index and score of the closest template.

    Maximum, not mean. Templates deliberately cover different poses; averaging
    across them penalises exactly the diversity multi-shot enrollment exists to
    capture (docs/08-ai-workflow.md §1).
    """
    if not templates:
        return -1, -1.0
    stacked = np.vstack([t.ravel() for t in templates])
    scores = stacked @ probe.ravel()
    index = int(np.argmax(scores))
    return index, float(scores[index])
