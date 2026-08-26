"""The production engine: SCRFD-10GF detection + ArcFace R50 embedding.

Every configuration choice here is a Phase 0 measurement, not a default —
see [docs/14-phase-0-spike.md](../../../../../docs/14-phase-0-spike.md).

* **Sessions are constructed here, not by `FaceAnalysis`.** ONNX Runtime
  defaults `intra_op_num_threads` to 0, meaning "every visible core", and a
  container sees the host's core count regardless of its CPU quota. Left at the
  default under a 2-CPU limit, the pipeline measured **five times slower**
  (p95 1674 ms vs 331 ms) purely from thread thrashing. `FaceAnalysis` offers no
  way to set it, and passing it through `provider_options` is accepted and
  silently ignored — it is a *session* option.

* **`det_size` defaults to 320, not 640.** Detection at 640 costs ~2.5x more
  (303 ms vs 121 ms at two threads) for recall the 112 px inter-ocular gate
  discards anyway.

* **Only two models are loaded.** `allowed_modules` excludes the 3D landmark,
  2D landmark and gender/age models — 143 MB of weights this product never uses.

* **Loaded once at startup**, never lazily. Warm load is ~1 s; a lazy first
  request would hand the first user of every deploy a multi-second verification.

The heavy imports are deferred to `__init__` so the module can be imported —
and the class referenced by the registry — without `insightface`, `onnxruntime`
or `opencv` installed. That is what lets `FACE_ENGINE=fake` run against a
dependency set that omits them entirely.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import structlog
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

logger = structlog.get_logger(__name__)

MODEL_PACK = "buffalo_l"
DETECTION_MODEL = "det_10g.onnx"
RECOGNITION_MODEL = "w600k_r50.onnx"


class MissingFaceDependenciesError(RuntimeError):
    """Raised when the real engine is requested without its optional extras."""


class InsightFaceEngine:
    """CPU inference over ONNX Runtime."""

    def __init__(
        self,
        *,
        model_pack: str = MODEL_PACK,
        model_root: Path | None = None,
        det_size: int = 320,
        threads: int = 2,
        det_threshold: float = 0.5,
        thresholds: QualityThresholds | None = None,
    ) -> None:
        try:
            import onnxruntime as ort
            from insightface.model_zoo.arcface_onnx import ArcFaceONNX
            from insightface.model_zoo.scrfd import SCRFD
        except ImportError as exc:  # pragma: no cover - exercised by deployment, not CI
            raise MissingFaceDependenciesError(
                "FACE_ENGINE=insightface requires the 'face' extra. "
                "Install it with: uv sync --extra face"
            ) from exc

        self._thresholds = thresholds or QualityThresholds()

        self._model_pack = model_pack
        root = model_root or (Path.home() / ".insightface" / "models" / model_pack)
        detection_path = root / DETECTION_MODEL
        recognition_path = root / RECOGNITION_MODEL
        for path in (detection_path, recognition_path):
            if not path.exists():
                raise MissingFaceDependenciesError(
                    f"Model file not found: {path}. The image should bake these in; "
                    "see docs/11-deployment.md §4."
                )

        def build_session(path: Path) -> Any:
            options = ort.SessionOptions()
            # The setting that matters. See the module docstring.
            options.intra_op_num_threads = threads
            options.inter_op_num_threads = 1
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            # SCRFD's graph declares output shapes for a 640x640 baseline and
            # logs a warning per output per frame at any other size. At 320 that
            # is nine warnings per verification.
            options.log_severity_level = 3
            return ort.InferenceSession(
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )

        self._detector = SCRFD(
            model_file=str(detection_path), session=build_session(detection_path)
        )
        # `prepare` is the only place det_thresh can be set — SCRFD reads it
        # from the instance, not from `detect()`.
        self._detector.prepare(ctx_id=-1, input_size=(det_size, det_size), det_thresh=det_threshold)

        self._recognizer = ArcFaceONNX(
            model_file=str(recognition_path), session=build_session(recognition_path)
        )
        self._recognizer.prepare(ctx_id=-1)

        logger.info(
            "face_engine_loaded",
            model=model_pack,
            det_size=det_size,
            intra_op_threads=threads,
        )

    @property
    def model(self) -> ModelInfo:
        # The recognition model, not the pack — it is what produced the
        # embedding, and it is what a future upgrade would invalidate.
        return ModelInfo(name=self._model_pack, version="w600k_r50", embedding_dim=512)

    # ── Protocol ─────────────────────────────────────────────────────────────

    def detect(self, image: NDArray[np.uint8]) -> list[DetectedFace]:
        bboxes, keypoints = self._detector.detect(image, max_num=0, metric="default")
        if bboxes.shape[0] == 0:
            return []

        faces = [self._to_face(bboxes[index], keypoints[index]) for index in range(bboxes.shape[0])]
        # Largest first, so callers that take faces[0] get the subject rather
        # than a bystander in the background.
        faces.sort(key=lambda f: f.bbox.width * f.bbox.height, reverse=True)
        return faces

    def assess_quality(
        self, image: NDArray[np.uint8], face: DetectedFace, *, strict: bool
    ) -> QualityReport:
        thresholds = self._thresholds if strict else self._thresholds.relaxed()
        return assess(image, face, thresholds)

    def embed(self, image: NDArray[np.uint8], face: DetectedFace) -> Embedding:
        from insightface.utils import face_align

        # Similarity transform from the five landmarks to ArcFace's canonical
        # 112x112 layout. Matching training-time preprocessing is not optional:
        # a mismatch silently destroys accuracy rather than erroring.
        aligned = face_align.norm_crop(image, landmark=face.landmarks, image_size=112)
        raw = self._recognizer.get_feat(aligned)
        vector = np.asarray(raw, dtype=np.float32).ravel()

        norm = float(np.linalg.norm(vector))
        if norm == 0.0:  # pragma: no cover - would mean a broken model
            raise ValueError("embedding has zero norm")
        return (vector / norm).astype(np.float32)

    # ── Internals ────────────────────────────────────────────────────────────

    def _to_face(self, bbox: NDArray[np.float32], landmarks: NDArray[np.float32]) -> DetectedFace:
        x1, y1, x2, y2, score = (float(v) for v in bbox[:5])
        points = np.asarray(landmarks, dtype=np.float32).reshape(5, 2)
        return DetectedFace(
            bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2, score=score),
            landmarks=points,
            pose=self._estimate_pose(points),
            inter_ocular_px=float(np.linalg.norm(points[1] - points[0])),
        )

    @staticmethod
    def _estimate_pose(landmarks: NDArray[np.float32]) -> Pose:
        """Approximate head pose from the five landmarks.

        Not a full PnP solve — that needs a 3D face model and camera intrinsics
        we do not have, and would add cost to the hot path for a gate that only
        needs to reject obviously-turned heads.

        * **roll** is exact: the angle of the inter-ocular line.
        * **yaw** comes from where the nose sits between the eyes; centred means
          facing forward, displaced means turned.
        * **pitch** compares the nose's vertical position against the eye-mouth
          span.

        Both approximations are monotonic in the true angle, which is all a
        threshold gate requires. Calibrating them against measured pose is
        listed as outstanding in docs/14 §8.
        """
        left_eye, right_eye, nose, left_mouth, right_mouth = landmarks

        eye_delta = right_eye - left_eye
        roll = float(np.degrees(np.arctan2(eye_delta[1], eye_delta[0])))

        eye_centre = (left_eye + right_eye) / 2.0
        eye_distance = float(np.linalg.norm(eye_delta)) or 1.0

        # Horizontal nose offset as a fraction of eye separation. ±0.5 of the
        # eye distance corresponds to roughly ±45°.
        yaw = float(np.clip((nose[0] - eye_centre[0]) / eye_distance, -1.0, 1.0) * 90.0)

        mouth_centre = (left_mouth + right_mouth) / 2.0
        vertical_span = float(mouth_centre[1] - eye_centre[1]) or 1.0
        # Nose sits ~45% of the way from eyes to mouth on a level head.
        nose_fraction = (nose[1] - eye_centre[1]) / vertical_span
        pitch = float(np.clip((nose_fraction - 0.45) * 3.0, -1.0, 1.0) * 90.0)

        return Pose(yaw=yaw, pitch=pitch, roll=roll)
