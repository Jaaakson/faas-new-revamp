"""Deterministic engine for tests and CI.

No model download, no ONNX Runtime, no OpenCV — the whole suite runs in seconds
against this. It is the concrete payoff of the `FaceEngine` protocol, and it is
what lets CI stay under two minutes instead of ten
(docs/05-architecture.md §7).

It is a *stand-in*, not a simulator. It does not model detection or the
behaviour of a real embedding space. What it guarantees is exactly what tests
need:

* the same image always produces the same embedding,
* frames tagged with the same identity match above the threshold,
* different identities do not,
* quality and geometry are controllable, so gate behaviour is testable without
  having to source a genuinely blurry photograph.

Crucially, the **production gate code runs unmodified** against these frames —
`assess_quality` synthesises a patch whose measured sharpness, brightness and
contrast match what the test asked for, then calls the real `assess()`. The
gates under test are the real ones, not mocks.

Test images carry their intent in a header rather than in engine state, so a
request can travel through HTTP, a service, and the ORM and still mean what the
test said.
"""

from __future__ import annotations

import hashlib
import struct

import numpy as np
from numpy.typing import NDArray

from app.modules.biometrics.engine.base import (
    BoundingBox,
    DetectedFace,
    Embedding,
    ModelInfo,
    Pose,
    QualityReport,
)
from app.modules.biometrics.engine.quality import QualityThresholds, assess

# Magic bytes marking a synthetic frame. Real JPEG/PNG data never begins with
# this, so a real image can never be mistaken for a scripted one.
MAGIC = b"FVASFAKE"
HEADER = struct.Struct("<8sI5fI")  # magic, identity, quality, brightness, yaw, pitch, roll, faces

PATCH_SIZE = 400
# A period-4 sinusoid is the high-frequency carrier whose amplitude sets the
# measured Laplacian variance. Chosen because the relationship is exact:
# for period 4 the discrete Laplacian eigenvalue is -2, so variance = 2A².
_DETAIL_PERIOD = 4
_SHARPNESS_CEILING = 500.0  # matches quality.sharpness()'s normalisation


def synthetic_image(
    identity: int = 1,
    *,
    quality: float = 0.9,
    brightness: float = 0.5,
    yaw: float = 0.0,
    pitch: float = 0.0,
    roll: float = 0.0,
    faces: int = 1,
) -> bytes:
    """Build a frame the fake engine interprets as described.

    `identity` drives the embedding: frames sharing one identity match, others
    do not. `quality` drives face size, sharpness and detector confidence
    together, the way a distant or blurred capture degrades all three at once.
    `brightness` is separate so the exposure gate can be tested on its own.
    """
    header = HEADER.pack(MAGIC, identity, quality, brightness, yaw, pitch, roll, faces)
    return header + b"\x00" * (2048 - len(header))


def _parse(payload: bytes) -> tuple[int, float, float, float, float, float, int] | None:
    if len(payload) < HEADER.size or not payload.startswith(MAGIC):
        return None
    magic, identity, quality, brightness, yaw, pitch, roll, faces = HEADER.unpack_from(payload)
    if magic != MAGIC:
        return None
    return identity, quality, brightness, yaw, pitch, roll, faces


class FakeFaceEngine:
    """A `FaceEngine` that needs nothing but numpy."""

    def __init__(self, thresholds: QualityThresholds | None = None) -> None:
        self._thresholds = thresholds or QualityThresholds()

    @property
    def model(self) -> ModelInfo:
        # A distinct name, so a template built here can never be silently
        # compared against one from InsightFace. The mismatch is detectable
        # rather than a quiet accuracy collapse (docs/08-ai-workflow.md §7).
        return ModelInfo(name="fake", version="v1", embedding_dim=512)

    # ── Protocol ─────────────────────────────────────────────────────────────

    def detect(self, image: NDArray[np.uint8]) -> list[DetectedFace]:
        spec = _parse(image.tobytes())
        if spec is None:
            # Unscripted bytes: one well-formed face, so a test can pass
            # arbitrary content without configuring anything.
            return [self._face(quality=0.9, brightness=0.5, yaw=0.0, pitch=0.0, roll=0.0)]

        _identity, quality, bright, yaw, pitch, roll, faces = spec
        return [
            self._face(quality=quality, brightness=bright, yaw=yaw, pitch=pitch, roll=roll)
            for _ in range(faces)
        ]

    def assess_quality(
        self, image: NDArray[np.uint8], face: DetectedFace, *, strict: bool
    ) -> QualityReport:
        thresholds = self._thresholds if strict else self._thresholds.relaxed()
        spec = _parse(image.tobytes())
        brightness = spec[2] if spec else 0.5
        return assess(self._patch_for(face, brightness), face, thresholds)

    def embed(self, image: NDArray[np.uint8], face: DetectedFace) -> Embedding:
        spec = _parse(image.tobytes())
        identity = spec[0] if spec else 0

        # Identity fixes the direction; the rest of the bytes add a small
        # per-capture jitter, so two frames of one person are close but not
        # identical — which is what makes multi-template enrollment and
        # best-of-N matching meaningful in tests.
        base = self._unit_vector(f"identity:{identity}")
        jitter = self._unit_vector(hashlib.sha256(image.tobytes()).hexdigest())
        combined = base * 0.97 + jitter * 0.03
        return (combined / np.linalg.norm(combined)).astype(np.float32)

    # ── Internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _unit_vector(seed: str) -> NDArray[np.float32]:
        digest = hashlib.sha256(seed.encode()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
        vector = rng.normal(size=512).astype(np.float32)
        return vector / np.linalg.norm(vector)

    def _face(
        self, *, quality: float, brightness: float, yaw: float, pitch: float, roll: float
    ) -> DetectedFace:
        # Inter-ocular distance scales with quality, so a low-quality frame
        # trips the size gate the way a distant subject would. Quality ~0.45
        # sits on the 112 px enrollment threshold — use values either side of
        # it rather than on it, since float32 rounding decides the boundary.
        inter_ocular = 40.0 + 160.0 * quality
        half = inter_ocular * 1.6
        landmarks = np.array(
            [
                [200 - inter_ocular / 2, 190],
                [200 + inter_ocular / 2, 190],
                [200, 215],
                [200 - inter_ocular / 3, 245],
                [200 + inter_ocular / 3, 245],
            ],
            dtype=np.float32,
        )
        return DetectedFace(
            bbox=BoundingBox(
                x1=200 - half,
                y1=200 - half,
                x2=200 + half,
                y2=200 + half,
                score=float(np.clip(0.35 + 0.65 * quality, 0.0, 1.0)),
            ),
            landmarks=landmarks,
            pose=Pose(yaw=yaw, pitch=pitch, roll=roll),
            inter_ocular_px=inter_ocular,
        )

    def _patch_for(self, face: DetectedFace, brightness: float) -> NDArray[np.uint8]:
        """A patch whose measured statistics match the requested quality.

        Built analytically rather than from noise. White noise has *maximal*
        Laplacian variance, so a noise-based "low quality" patch would measure
        as perfectly sharp — the opposite of the intent. A period-4 sinusoid
        gives an exact handle instead: the discrete Laplacian eigenvalue is -2,
        so variance = 2A², and amplitude A = sqrt(ceiling * quality / 2) lands
        `sharpness()` on the requested value.
        """
        quality = float(np.clip((face.bbox.score - 0.35) / 0.65, 0.0, 1.0))

        y, x = np.mgrid[0:PATCH_SIZE, 0:PATCH_SIZE].astype(np.float32)

        # Low-frequency structure keeps contrast realistic without contributing
        # meaningfully to the Laplacian.
        structure = 30.0 * np.sin(2 * np.pi * x / 120.0) * np.cos(2 * np.pi * y / 160.0)

        amplitude = float(np.sqrt(_SHARPNESS_CEILING * quality / 2.0))
        detail = amplitude * np.sin(2 * np.pi * x / _DETAIL_PERIOD)

        raw = np.clip(brightness * 255.0 + structure + detail, 0, 255)
        patch: NDArray[np.uint8] = raw.astype(np.uint8)
        return patch
