"""Engine selection and lifetime.

The engine is a process-wide singleton created once during startup, because
loading ONNX weights takes ~1 s and holding two copies of a 182 MB model would
double the memory footprint of every worker.

`FACE_ENGINE` selects the implementation:

* `fake` — deterministic, no dependencies. The default in tests and CI.
* `insightface` — the real pipeline. Requires the `face` extra.
"""

from __future__ import annotations

import structlog

from app.core.config import settings
from app.modules.biometrics.engine.base import FaceEngine
from app.modules.biometrics.engine.fake import FakeFaceEngine
from app.modules.biometrics.engine.quality import QualityThresholds

logger = structlog.get_logger(__name__)

_engine: FaceEngine | None = None


def build_engine() -> FaceEngine:
    """Construct the configured engine. Raises rather than falling back.

    A silent fallback to the fake engine in production would mean accepting
    every face — the failure mode must be a refusal to start.
    """
    thresholds = QualityThresholds(
        min_inter_ocular_px=settings.MIN_FACE_SIZE_PX,
        min_sharpness=settings.MIN_SHARPNESS,
        min_brightness=settings.MIN_BRIGHTNESS,
        max_brightness=settings.MAX_BRIGHTNESS,
        max_yaw_deg=settings.MAX_YAW_DEGREES,
        max_pitch_deg=settings.MAX_PITCH_DEGREES,
        max_roll_deg=settings.MAX_ROLL_DEGREES,
    )

    if settings.FACE_ENGINE == "fake":
        if settings.is_production:
            raise RuntimeError(
                "FACE_ENGINE=fake in production would accept any face. Refusing to start."
            )
        return FakeFaceEngine(thresholds=thresholds)

    from app.modules.biometrics.engine.insightface_engine import InsightFaceEngine

    return InsightFaceEngine(
        model_pack=settings.FACE_MODEL_NAME,
        det_size=settings.FACE_DET_SIZE,
        threads=settings.ONNX_INTRA_OP_THREADS,
        det_threshold=settings.FACE_DET_THRESHOLD,
        thresholds=thresholds,
    )


def load_engine() -> FaceEngine:
    """Called from the app lifespan. Idempotent."""
    global _engine
    if _engine is None:
        _engine = build_engine()
        logger.info(
            "face_engine_ready",
            engine=settings.FACE_ENGINE,
            model=_engine.model.name,
            version=_engine.model.version,
        )
    return _engine


def get_engine() -> FaceEngine:
    """Dependency accessor. The engine must already be loaded."""
    if _engine is None:
        # Lazily constructing here would put a multi-second model load inside a
        # request, and inside whatever lock the event loop happens to hold.
        raise RuntimeError("Face engine not loaded. It is initialised in the app lifespan.")
    return _engine


def reset_engine() -> None:
    """Test hook — drops the singleton so a fixture can install its own."""
    global _engine
    _engine = None


def set_engine(engine: FaceEngine) -> None:
    """Test hook — installs a specific engine instance."""
    global _engine
    _engine = engine
