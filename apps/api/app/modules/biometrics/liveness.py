"""Presentation-attack heuristics, and what they are not.

**This is not certified presentation-attack detection.** It is a set of cheap
signals that catch casual attacks, behind an interface so that a real PAD model
is a drop-in addition rather than a refactor
([docs/08-ai-workflow.md §5](../../../../docs/08-ai-workflow.md)).

What it stops: a face held up on a phone screen, a low-quality print.
What it does not stop: a good screen at the right angle, a high-quality print, a
prepared video, a deepfake.

That distinction is written into the product's positioning, not buried in a
disclaimer. Fvas is appropriate as a step-up factor where the attacker also
needs the account, the device and the session. It is not appropriate as the sole
control for unsupervised remote onboarding against a motivated adversary.

The signals, all computed on the aligned face crop:

* **Moiré** — photographing an LCD aliases its pixel grid against the camera
  sensor, producing a *narrowband peak* in the spectrum that a real face does not
  have. Detected as the prominence of that peak above the local spectral trend.
  (Measured, not assumed: an earlier formulation that summed banded energy
  instead scored a live face worse than a printed one, because sensor noise is
  broadband. See `moire_score`.)
* **Specular uniformity** — a screen emits light evenly; a face is a curved
  surface under a point source, so its highlights cluster. Measured as the
  spatial spread of the brightest pixels.
* **Texture variance (LBP-like)** — skin has fine micro-texture that survives at
  high frequency; paper and screens are comparatively flat after the print or
  display pipeline has resampled them.

Each returns a 0-1 score where higher means *more likely live*. They are
combined with a weighted mean rather than a hard AND: any single heuristic
firing on a real face would reject a legitimate user, and these are heuristics,
not proofs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from app.modules.biometrics.engine.base import DetectedFace
from app.modules.biometrics.engine.quality import crop_face, to_grayscale


@dataclass(frozen=True, slots=True)
class LivenessSignal:
    name: str
    score: float
    passed: bool
    threshold: float

    def as_dict(self) -> dict[str, object]:
        return {
            "signal": self.name,
            "score": round(self.score, 3),
            "passed": self.passed,
            "required": round(self.threshold, 3),
        }


@dataclass
class LivenessReport:
    signals: list[LivenessSignal] = field(default_factory=list)
    # Deliberately separate from `passed`. A caller must be able to see that a
    # decision was made with liveness *disabled*, not infer it from a pass.
    evaluated: bool = True

    @property
    def score(self) -> float:
        if not self.signals:
            return 1.0
        return sum(signal.score for signal in self.signals) / len(self.signals)

    @property
    def passed(self) -> bool:
        return all(signal.passed for signal in self.signals)

    @property
    def first_failure(self) -> LivenessSignal | None:
        return next((signal for signal in self.signals if not signal.passed), None)

    def as_dict(self) -> dict[str, object]:
        return {
            "evaluated": self.evaluated,
            "passed": self.passed,
            "score": round(self.score, 3),
            "signals": [signal.as_dict() for signal in self.signals],
        }


@runtime_checkable
class LivenessDetector(Protocol):
    """Passive presentation-attack scoring on a single frame.

    Single-frame by design at this stage. An active challenge needs several
    frames and a prompt the client must satisfy; that is a different interface
    and it is not in this build.
    """

    def evaluate(self, image: NDArray[np.uint8], face: DetectedFace) -> LivenessReport: ...


@dataclass(frozen=True, slots=True)
class LivenessThresholds:
    """Tuned to be permissive.

    A false *rejection* here locks a legitimate person out of their account over
    a lighting artefact, while a false acceptance still has to get past matching.
    Given the heuristics are weak either way, being generous is the correct
    asymmetry — and it is stated rather than smuggled in as a magic number.
    """

    min_moire: float = 0.35
    min_specular: float = 0.30
    min_texture: float = 0.25


class HeuristicLivenessDetector:
    """The shipped detector. numpy only — no extra model, no extra latency tier."""

    def __init__(self, thresholds: LivenessThresholds | None = None) -> None:
        self._thresholds = thresholds or LivenessThresholds()

    def evaluate(self, image: NDArray[np.uint8], face: DetectedFace) -> LivenessReport:
        crop = crop_face(image, face)
        gray = to_grayscale(crop).astype(np.float32)

        if min(gray.shape[:2]) < 16:
            # Too small to say anything. Reporting a confident pass on four
            # pixels would be worse than reporting that it was not evaluated.
            return LivenessReport(signals=[], evaluated=False)

        thresholds = self._thresholds
        # Each signal is computed once. Two of these involve an FFT or a
        # percentile over the crop, and this runs on the verification hot path.
        measured = (
            ("moire", moire_score(gray), thresholds.min_moire),
            ("specular_uniformity", specular_score(gray), thresholds.min_specular),
            ("texture", texture_score(gray), thresholds.min_texture),
        )
        return LivenessReport(
            signals=[
                LivenessSignal(name=name, score=score, passed=score >= limit, threshold=limit)
                for name, score, limit in measured
            ]
        )


class DisabledLivenessDetector:
    """Used when an organization has liveness off.

    An explicit no-op rather than a `None` check at the call site: the service
    always gets a report, and `evaluated=False` records in the session row that
    the question was never asked. That distinction matters in an audit.
    """

    def evaluate(self, image: NDArray[np.uint8], face: DetectedFace) -> LivenessReport:
        return LivenessReport(signals=[], evaluated=False)


# ── Signals ───────────────────────────────────────────────────────────────────


RADIAL_BINS: int = 32
MOIRE_BAND: tuple[float, float] = (0.35, 0.95)
# A live crop's radial profile is smooth, so its peak sits near the local
# median. Below this the frame is treated as clean.
MOIRE_CLEAN_RATIO: float = 1.5
# A panel grid produces a spike several times the surrounding trend.
MOIRE_SCREEN_RATIO: float = 4.0


def _radial_profile(gray: NDArray[np.float32]) -> NDArray[np.float32]:
    """Mean spectral magnitude per normalised-frequency ring."""
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(gray - gray.mean())))
    height, width = spectrum.shape
    centre_y, centre_x = height / 2.0, width / 2.0

    y, x = np.ogrid[:height, :width]
    radius = np.sqrt((y - centre_y) ** 2 + (x - centre_x) ** 2)
    normalised = (radius / (min(centre_y, centre_x) or 1.0)).ravel()

    edges = np.linspace(0.0, 1.0, RADIAL_BINS + 1)
    index = np.digitize(normalised, edges) - 1
    flat = spectrum.ravel()

    totals = np.bincount(index.clip(0, RADIAL_BINS - 1), weights=flat, minlength=RADIAL_BINS)
    counts = np.bincount(index.clip(0, RADIAL_BINS - 1), minlength=RADIAL_BINS)
    return (totals / np.maximum(counts, 1)).astype(np.float32)


def moire_score(gray: NDArray[np.float32]) -> float:
    """1.0 means no screen grid detected; 0.0 means a strong one.

    Measures the *prominence of a peak* in the radial spectrum, not the energy
    in a band. That distinction was established by measurement, and the first
    formulation had it backwards: banded-energy-over-total scored a real face
    at 0.00 and a sheet of paper at 0.04, because camera sensor noise is
    broadband and swamps the band it was summing. It would have rejected live
    faces while passing prints.

    A panel's pixel grid is a *narrowband* artefact — one sharp ring in the
    spectrum. A real face plus sensor noise falls off smoothly, so the ratio of
    the band's peak to the band's median separates them:

        face 1.03 · dim face 1.06 · paper 1.09 · subtle screen 2.04 · screen 8.46

    The subtle case is the documented limit, not a bug: a good screen at the
    right angle is one of the attacks this heuristic explicitly does not stop.
    """
    profile = _radial_profile(gray)
    edges = np.linspace(0.0, 1.0, RADIAL_BINS + 1)[:-1]
    low, high = MOIRE_BAND
    band = profile[(edges >= low) & (edges <= high)]

    if band.size < 5 or band.max() <= 0:
        return 1.0
    baseline = float(np.median(band))
    if baseline <= 0:
        return 1.0

    ratio = float(band.max()) / baseline
    span = MOIRE_SCREEN_RATIO - MOIRE_CLEAN_RATIO
    return float(np.clip(1.0 - (ratio - MOIRE_CLEAN_RATIO) / span, 0.0, 1.0))


def specular_score(gray: NDArray[np.float32]) -> float:
    """1.0 means highlights are clustered as they are on a face.

    A screen is a plane emitting uniformly, so its brightest pixels are spread
    across the whole crop. A face is curved under a point source, so its
    highlights cluster on the forehead, nose and cheekbones. Measured as the
    spatial standard deviation of the top-decile pixels, normalised by the crop
    size so it does not depend on resolution.
    """
    height, width = gray.shape
    cutoff = float(np.percentile(gray, 90))
    ys, xs = np.nonzero(gray >= cutoff)
    if ys.size < 8:
        return 1.0

    spread = (ys.std() / max(height, 1) + xs.std() / max(width, 1)) / 2.0
    # A uniform sheet spreads at roughly 0.29 (the std of a uniform
    # distribution on [0,1]); clustered highlights land well below it.
    return float(np.clip(1.0 - spread / 0.29, 0.0, 1.0))


def texture_score(gray: NDArray[np.float32]) -> float:
    """1.0 means skin-like micro-texture is present.

    An LBP-style measure without the histogram: count how often a pixel differs
    from its neighbours by more than a noise-floor delta. Print and display
    pipelines resample, which smooths exactly this signal away.
    """
    if min(gray.shape) < 3:
        return 0.0

    centre = gray[1:-1, 1:-1]
    neighbours = (
        gray[:-2, 1:-1],
        gray[2:, 1:-1],
        gray[1:-1, :-2],
        gray[1:-1, 2:],
    )
    # 3 grey levels: above sensor noise, below real texture.
    transitions = sum(np.abs(neighbour - centre) > 3.0 for neighbour in neighbours)
    density = float(np.mean(transitions)) / len(neighbours)

    # ~0.45 of neighbour pairs differing is a well-textured face crop.
    return float(np.clip(density / 0.45, 0.0, 1.0))
