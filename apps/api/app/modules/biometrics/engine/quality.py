"""Quality gates.

Run *before* embedding, for two reasons: a bad template poisons every future
verification against it, and rejecting early skips the expensive stage.

Every gate returns a score in [0, 1] alongside pass/fail, because the console
shows a quality number and the capture UI needs to know how close a frame was —
"almost sharp enough" and "hopelessly blurred" should not look the same.

Thresholds come from docs/08-ai-workflow.md §2. They are estimates, not
measurements: the Phase 0 spike measured latency and the matching threshold, and
explicitly did not measure these. Treat them as the next thing to calibrate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from app.modules.biometrics.engine.base import DetectedFace, GateResult, QualityReport


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    """Gate limits. Enrollment uses the strict set, verification the relaxed one."""

    min_inter_ocular_px: float = 112.0
    min_sharpness: float = 0.35
    min_brightness: float = 0.25
    max_brightness: float = 0.85
    min_contrast: float = 0.10
    max_yaw_deg: float = 25.0
    max_pitch_deg: float = 20.0
    max_roll_deg: float = 20.0
    min_detection_score: float = 0.60

    def relaxed(self) -> QualityThresholds:
        """Verification-time limits.

        Roughly 70% of the enrollment requirement on the gates a user can do
        something about, and unchanged on detector confidence — a low-confidence
        detection is not a judgement call.
        """
        return QualityThresholds(
            min_inter_ocular_px=self.min_inter_ocular_px * 0.7,
            min_sharpness=self.min_sharpness * 0.7,
            min_brightness=self.min_brightness * 0.7,
            max_brightness=min(1.0, self.max_brightness * 1.1),
            min_contrast=self.min_contrast * 0.7,
            max_yaw_deg=self.max_yaw_deg * 1.4,
            max_pitch_deg=self.max_pitch_deg * 1.4,
            max_roll_deg=self.max_roll_deg * 1.4,
            min_detection_score=self.min_detection_score,
        )


def _ratio_score(value: float, threshold: float, *, headroom: float = 2.0) -> float:
    """Score a "higher is better" gate.

    Reaches 1.0 at `headroom` times the threshold rather than at the threshold
    itself, so a frame that barely passes does not display as perfect.
    """
    if threshold <= 0:
        return 1.0
    return float(np.clip(value / (threshold * headroom), 0.0, 1.0))


def _band_score(value: float, low: float, high: float) -> float:
    """Score a "must sit inside a band" gate — 1.0 at the centre."""
    if value < low or value > high:
        # Distance outside the band, relative to its width.
        overshoot = (low - value) if value < low else (value - high)
        return float(np.clip(1.0 - overshoot / max(high - low, 1e-6), 0.0, 1.0))
    centre = (low + high) / 2
    half = (high - low) / 2
    return float(np.clip(1.0 - abs(value - centre) / max(half, 1e-6) * 0.4, 0.0, 1.0))


def _inverse_score(value: float, limit: float) -> float:
    """Score a "lower is better" gate, 1.0 at zero."""
    if limit <= 0:
        return 1.0
    return float(np.clip(1.0 - abs(value) / limit, 0.0, 1.0))


def sharpness(gray_face: NDArray[np.uint8]) -> float:
    """Variance of the Laplacian, normalised to roughly [0, 1].

    Motion blur is the top cause of false rejection in field use, and it is
    invisible in a thumbnail — which is why this is measured rather than left
    to the operator.
    """
    # 4-neighbour Laplacian via numpy so the gate works without OpenCV, keeping
    # the fake engine and its tests free of the heavy optional dependency.
    image = gray_face.astype(np.float32)
    laplacian = (
        -4.0 * image[1:-1, 1:-1]
        + image[:-2, 1:-1]
        + image[2:, 1:-1]
        + image[1:-1, :-2]
        + image[1:-1, 2:]
    )
    variance = float(laplacian.var())
    # 500 is a well-worn empirical ceiling for "definitely sharp" on 8-bit
    # imagery; it only affects the reported score, not the pass/fail boundary.
    return float(np.clip(variance / 500.0, 0.0, 1.0))


def brightness(gray_face: NDArray[np.uint8]) -> float:
    return float(gray_face.mean() / 255.0)


def contrast(gray_face: NDArray[np.uint8]) -> float:
    return float(gray_face.std() / 128.0)


def to_grayscale(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """BGR to luminance. ITU-R BT.601 weights."""
    if image.ndim == 2:
        return image
    blue, green, red = image[..., 0], image[..., 1], image[..., 2]
    gray: NDArray[np.uint8] = (0.114 * blue + 0.587 * green + 0.299 * red).astype(np.uint8)
    return gray


def crop_face(image: NDArray[np.uint8], face: DetectedFace) -> NDArray[np.uint8]:
    """The face region, clamped to the frame.

    Gates measure the *face*, not the frame: a dim subject against a bright
    window should fail the brightness gate, and would not if the whole image
    were averaged.
    """
    height, width = image.shape[:2]
    x1 = max(0, int(face.bbox.x1))
    y1 = max(0, int(face.bbox.y1))
    x2 = min(width, int(face.bbox.x2))
    y2 = min(height, int(face.bbox.y2))
    if x2 <= x1 or y2 <= y1:
        return image
    return image[y1:y2, x1:x2]


def assess(
    image: NDArray[np.uint8],
    face: DetectedFace,
    thresholds: QualityThresholds,
) -> QualityReport:
    """Run every gate and report all outcomes."""
    face_region = crop_face(image, face)
    gray = to_grayscale(face_region)

    # Guard against a degenerate crop making the Laplacian window empty.
    sharp = sharpness(gray) if min(gray.shape[:2]) >= 3 else 0.0
    bright = brightness(gray)
    contrast_value = contrast(gray)

    gates = [
        GateResult(
            name="min_face_size",
            passed=face.inter_ocular_px >= thresholds.min_inter_ocular_px,
            score=_ratio_score(face.inter_ocular_px, thresholds.min_inter_ocular_px, headroom=1.6),
            value=face.inter_ocular_px,
            threshold=thresholds.min_inter_ocular_px,
        ),
        GateResult(
            name="sharpness",
            passed=sharp >= thresholds.min_sharpness,
            score=_ratio_score(sharp, thresholds.min_sharpness, headroom=1.8),
            value=sharp,
            threshold=thresholds.min_sharpness,
        ),
        GateResult(
            name="brightness",
            passed=thresholds.min_brightness <= bright <= thresholds.max_brightness,
            score=_band_score(bright, thresholds.min_brightness, thresholds.max_brightness),
            value=bright,
            threshold=thresholds.min_brightness,
        ),
        GateResult(
            name="contrast",
            passed=contrast_value >= thresholds.min_contrast,
            score=_ratio_score(contrast_value, thresholds.min_contrast, headroom=2.5),
            value=contrast_value,
            threshold=thresholds.min_contrast,
        ),
        GateResult(
            name="pose_yaw",
            passed=abs(face.pose.yaw) <= thresholds.max_yaw_deg,
            score=_inverse_score(face.pose.yaw, thresholds.max_yaw_deg),
            value=face.pose.yaw,
            threshold=thresholds.max_yaw_deg,
        ),
        GateResult(
            name="pose_pitch",
            passed=abs(face.pose.pitch) <= thresholds.max_pitch_deg,
            score=_inverse_score(face.pose.pitch, thresholds.max_pitch_deg),
            value=face.pose.pitch,
            threshold=thresholds.max_pitch_deg,
        ),
        GateResult(
            name="pose_roll",
            passed=abs(face.pose.roll) <= thresholds.max_roll_deg,
            score=_inverse_score(face.pose.roll, thresholds.max_roll_deg),
            value=face.pose.roll,
            threshold=thresholds.max_roll_deg,
        ),
        GateResult(
            name="detection_confidence",
            passed=face.bbox.score >= thresholds.min_detection_score,
            score=_ratio_score(face.bbox.score, thresholds.min_detection_score, headroom=1.4),
            value=face.bbox.score,
            threshold=thresholds.min_detection_score,
        ),
    ]
    return QualityReport(gates=gates)


# Machine-readable reasons, surfaced verbatim in the API error envelope so a
# client can branch on them, paired with copy a capture UI can show a user.
GATE_GUIDANCE: dict[str, str] = {
    "min_face_size": "Move closer to the camera.",
    "sharpness": "Hold still — the image is blurred.",
    "brightness": "Adjust the lighting; the image is too dark or too bright.",
    "contrast": "Increase the lighting contrast on your face.",
    "pose_yaw": "Face the camera directly.",
    "pose_pitch": "Level your head with the camera.",
    "pose_roll": "Straighten your head.",
    "detection_confidence": "Make sure your whole face is visible and unobstructed.",
}
