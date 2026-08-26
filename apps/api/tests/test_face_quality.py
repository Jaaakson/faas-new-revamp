"""Quality gates, the frame pipeline, and image decoding.

Unit tests, no database and no HTTP. These cover the layer where a mistake is
silent: a gate that never fires, a pose threshold with an inverted sign, or a
decoder that hands the model an RGB frame it expects to be BGR. None of those
raise — they just quietly degrade accuracy, which is the hardest kind of bug to
find later.

The gates under test are the production ones. `FakeFaceEngine` synthesises a
patch whose *measured* statistics match what the test asked for and then calls
the real `assess()`; nothing here is a mock.
"""

from __future__ import annotations

import base64
import io

import numpy as np
import pytest
from PIL import Image

from app.core.exceptions import BadRequestError, PayloadTooLargeError
from app.modules.biometrics.engine.base import best_match, cosine_similarity
from app.modules.biometrics.engine.fake import FakeFaceEngine, synthetic_image
from app.modules.biometrics.engine.quality import QualityThresholds
from app.modules.biometrics.images import (
    MAX_DIMENSION,
    decode_base64,
    decode_image,
    load_images,
)
from app.modules.biometrics.pipeline import (
    LOW_QUALITY,
    MULTIPLE_FACES,
    NO_FACE_DETECTED,
    process_frames,
)


@pytest.fixture
def engine() -> FakeFaceEngine:
    return FakeFaceEngine()


def _assess(engine: FakeFaceEngine, image_bytes: bytes, *, strict: bool = True):  # type: ignore[no-untyped-def]
    frame = np.frombuffer(image_bytes, dtype=np.uint8)
    faces = engine.detect(frame)
    return engine.assess_quality(frame, faces[0], strict=strict)


# ── Gates ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("kwargs", "expected_gate"),
    [
        ({"quality": 0.15}, "min_face_size"),
        ({"brightness": 0.05}, "brightness"),
        ({"brightness": 0.98}, "brightness"),
        ({"yaw": 45.0}, "pose_yaw"),
        ({"pitch": 40.0}, "pose_pitch"),
        ({"roll": 40.0}, "pose_roll"),
    ],
)
def test_each_gate_rejects_the_condition_it_exists_for(
    engine: FakeFaceEngine, kwargs: dict, expected_gate: str
) -> None:
    report = _assess(engine, synthetic_image(1, **kwargs))

    assert not report.passed
    failed = {gate.name for gate in report.gates if not gate.passed}
    assert expected_gate in failed, f"expected {expected_gate} to fail, got {failed or 'none'}"


def test_a_good_frame_passes_every_gate(engine: FakeFaceEngine) -> None:
    report = _assess(engine, synthetic_image(1, quality=0.9, brightness=0.5))

    assert report.passed, [gate.name for gate in report.gates if not gate.passed]
    assert report.score > 0.8


def test_the_report_lists_every_gate_not_just_the_first_failure(engine: FakeFaceEngine) -> None:
    """A capture UI has to coach the user once, not once per round trip."""
    report = _assess(engine, synthetic_image(1, quality=0.15, brightness=0.05, yaw=45.0))

    names = [gate.name for gate in report.gates]
    assert len(names) == len(set(names)) == 8
    failed = {gate.name for gate in report.gates if not gate.passed}
    assert {"min_face_size", "brightness", "pose_yaw"} <= failed


def test_gate_scores_are_graded_rather_than_binary(engine: FakeFaceEngine) -> None:
    """ "Almost sharp enough" and "hopelessly blurred" must not look the same."""
    marginal = _assess(engine, synthetic_image(1, yaw=24.0))
    hopeless = _assess(engine, synthetic_image(1, yaw=90.0))

    marginal_yaw = next(g for g in marginal.gates if g.name == "pose_yaw")
    hopeless_yaw = next(g for g in hopeless.gates if g.name == "pose_yaw")

    assert marginal_yaw.passed and not hopeless_yaw.passed
    assert marginal_yaw.score > hopeless_yaw.score
    assert 0.0 <= hopeless_yaw.score < 0.2


def test_verification_thresholds_are_looser_than_enrollment_thresholds() -> None:
    """Someone enrolling can retake a photo. Someone authenticating at 11pm in a
    badly lit warehouse cannot.
    """
    strict = QualityThresholds()
    relaxed = strict.relaxed()

    assert relaxed.min_inter_ocular_px < strict.min_inter_ocular_px
    assert relaxed.min_sharpness < strict.min_sharpness
    assert relaxed.max_yaw_deg > strict.max_yaw_deg
    # Detector confidence is not a judgement call, so it is not relaxed.
    assert relaxed.min_detection_score == strict.min_detection_score


def test_a_frame_rejected_for_enrollment_can_still_verify(engine: FakeFaceEngine) -> None:
    """The point of the split, stated as a behaviour rather than a constant."""
    marginal = synthetic_image(1, quality=0.9, yaw=30.0)

    assert not _assess(engine, marginal, strict=True).passed
    assert _assess(engine, marginal, strict=False).passed


# ── Embeddings ────────────────────────────────────────────────────────────────


def test_the_same_frame_always_produces_the_same_embedding(engine: FakeFaceEngine) -> None:
    frame = np.frombuffer(synthetic_image(1), dtype=np.uint8)
    face = engine.detect(frame)[0]

    first = engine.embed(frame, face)
    second = engine.embed(frame, face)

    assert cosine_similarity(first, second) == pytest.approx(1.0)


def test_captures_of_one_identity_match_and_different_identities_do_not(
    engine: FakeFaceEngine,
) -> None:
    def embed(identity: int, salt: int) -> np.ndarray:
        payload = bytearray(synthetic_image(identity))
        payload[-4:] = salt.to_bytes(4, "little")
        frame = np.frombuffer(bytes(payload), dtype=np.uint8)
        return engine.embed(frame, engine.detect(frame)[0])

    same = cosine_similarity(embed(1, 1), embed(1, 2))
    different = cosine_similarity(embed(1, 1), embed(2, 1))

    assert same > 0.9
    assert different < 0.3
    # Two captures of one person must not be *identical*, or multi-template
    # enrollment would be measuring nothing.
    assert same < 1.0


def test_best_match_takes_the_maximum_not_the_mean() -> None:
    """Templates deliberately cover different poses; averaging penalises exactly
    the diversity multi-shot enrollment exists to capture.
    """
    probe = np.zeros(512, dtype=np.float32)
    probe[0] = 1.0

    near = np.zeros(512, dtype=np.float32)
    near[0] = 1.0
    far = np.zeros(512, dtype=np.float32)
    far[1] = 1.0

    index, score = best_match(probe, [far, near, far])

    assert index == 1
    assert score == pytest.approx(1.0)


def test_best_match_on_an_empty_template_set_is_not_a_match() -> None:
    index, score = best_match(np.zeros(512, dtype=np.float32), [])
    assert index == -1
    assert score < 0


# ── Pipeline ──────────────────────────────────────────────────────────────────


def _frames(*payloads: bytes) -> list[np.ndarray]:
    return [np.frombuffer(payload, dtype=np.uint8) for payload in payloads]


def test_every_frame_is_processed_even_after_one_fails(engine: FakeFaceEngine) -> None:
    outcome = process_frames(
        engine,
        _frames(
            synthetic_image(1, quality=0.15),
            synthetic_image(1, quality=0.9),
            synthetic_image(1, brightness=0.02),
        ),
        strict=True,
    )

    assert len(outcome.frames) == 3
    assert [frame.accepted for frame in outcome.frames] == [False, True, False]
    assert len(outcome.accepted) == 1


def test_a_frame_with_two_faces_is_refused_rather_than_disambiguated(
    engine: FakeFaceEngine,
) -> None:
    """Enrolling the wrong person from a frame with a bystander produces a
    profile that silently authenticates the wrong human forever.
    """
    outcome = process_frames(engine, _frames(synthetic_image(1, faces=2)), strict=True)

    assert outcome.frames[0].reason == MULTIPLE_FACES
    assert not outcome.accepted


def test_a_frame_with_no_face_reports_no_face(engine: FakeFaceEngine) -> None:
    outcome = process_frames(engine, _frames(synthetic_image(1, faces=0)), strict=True)

    assert outcome.frames[0].reason == NO_FACE_DETECTED
    assert outcome.frames[0].guidance


def test_the_reported_reason_is_the_most_common_not_the_first(engine: FakeFaceEngine) -> None:
    """Telling a user "no face detected" because frame 0 was a wall, when the
    other three were merely blurred, sends them to fix the wrong thing.
    """
    outcome = process_frames(
        engine,
        _frames(
            synthetic_image(1, faces=0),
            synthetic_image(1, quality=0.15),
            synthetic_image(1, quality=0.15),
            synthetic_image(1, quality=0.15),
        ),
        strict=True,
    )

    assert outcome.frames[0].reason == NO_FACE_DETECTED
    assert outcome.dominant_reason == LOW_QUALITY


def test_a_caller_supplied_quality_floor_applies_on_top_of_the_gates(
    engine: FakeFaceEngine,
) -> None:
    good = _frames(synthetic_image(1, quality=0.9))

    assert process_frames(engine, good, strict=True).accepted
    assert not process_frames(engine, good, strict=True, min_quality=0.99).accepted


def test_rejected_frames_never_carry_an_embedding(engine: FakeFaceEngine) -> None:
    """Gating runs before embedding — a rejected frame must not have paid for the
    most expensive stage in the pipeline.
    """
    outcome = process_frames(engine, _frames(synthetic_image(1, quality=0.15)), strict=True)

    assert outcome.frames[0].embedding is None
    assert outcome.embed_ms == 0


def test_every_failure_carries_both_a_code_and_human_guidance(engine: FakeFaceEngine) -> None:
    """The code is for the integrator's switch; the guidance is for their user.
    Returning only one of the two makes every integration either brittle or
    unhelpful.
    """
    outcome = process_frames(
        engine,
        _frames(
            synthetic_image(1, faces=0),
            synthetic_image(1, faces=2),
            synthetic_image(1, quality=0.15),
            synthetic_image(1, brightness=0.02),
        ),
        strict=True,
    )

    for frame in outcome.frames:
        assert not frame.accepted
        assert frame.reason, f"frame {frame.index} has no reason code"
        assert frame.guidance, f"frame {frame.index} has no user-facing guidance"


# ── Image decoding ────────────────────────────────────────────────────────────


def _jpeg(
    width: int = 400, height: int = 400, colour: tuple[int, int, int] = (10, 20, 200)
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def test_a_real_jpeg_decodes_to_a_bgr_array() -> None:
    """Channel order is not cosmetic. InsightFace's preprocessing was trained on
    OpenCV's BGR; handing it RGB does not raise, it silently costs accuracy.
    """
    # Pure red in RGB. In BGR it must come back as (0, 0, 255) — the value
    # belongs in the LAST channel. JPEG is lossy, hence the tolerances.
    array = decode_image(_jpeg(colour=(255, 0, 0)))

    assert array.shape == (400, 400, 3)
    assert array.dtype == np.uint8

    blue, green, red = (int(channel) for channel in array[200, 200])
    assert red > 200, f"red ended up in the wrong channel: BGR={(blue, green, red)}"
    assert blue < 50 and green < 50


def test_a_data_url_is_accepted_as_well_as_bare_base64() -> None:
    """`canvas.toDataURL()` produces the prefixed form, and making integrators
    strip it is a pointless source of support tickets.
    """
    encoded = base64.b64encode(_jpeg()).decode()

    bare = decode_image(decode_base64(encoded))
    prefixed = decode_image(decode_base64(f"data:image/jpeg;base64,{encoded}"))

    assert np.array_equal(bare, prefixed)


def test_a_decompression_bomb_is_refused_on_its_declared_size() -> None:
    """A small PNG can declare enormous dimensions and allocate gigabytes on
    decode. The header is read first so nothing is ever allocated.
    """
    buffer = io.BytesIO()
    Image.new("RGB", (MAX_DIMENSION + 1, 100)).save(buffer, format="PNG")

    with pytest.raises(PayloadTooLargeError) as error:
        decode_image(buffer.getvalue())

    assert error.value.details is not None
    assert error.value.details["width"] == MAX_DIMENSION + 1


def test_an_oversized_payload_is_rejected_before_it_is_decoded() -> None:
    """Checked on the encoded length, so the 4/3 expansion never happens."""
    from app.core.config import settings

    oversized = "A" * (settings.MAX_IMAGE_SIZE_MB * 1024 * 1024 * 2)

    with pytest.raises(PayloadTooLargeError):
        decode_base64(oversized)


@pytest.mark.parametrize(
    "payload",
    [
        b"not an image at all",
        b"\xff\xd8\xff\xe0 truncated jpeg header only",
        b"PK\x03\x04 a zip pretending to be a jpeg",
    ],
)
def test_non_image_bytes_are_rejected_as_invalid_images(payload: bytes) -> None:
    with pytest.raises(BadRequestError) as error:
        decode_image(payload)

    assert error.value.code == "invalid_image"


def test_an_empty_payload_is_rejected() -> None:
    with pytest.raises(BadRequestError):
        decode_base64("")


def test_a_tiny_image_is_rejected_before_detection() -> None:
    with pytest.raises(BadRequestError) as error:
        decode_image(_jpeg(width=32, height=32))

    assert error.value.code == "invalid_image"


def test_the_failing_frame_is_identified_by_index() -> None:
    """A capture UI submitting five frames needs to know which one to retake."""
    good = base64.b64encode(_jpeg()).decode()

    with pytest.raises(BadRequestError) as error:
        load_images([good, good, "@@@ not base64 @@@"])

    assert error.value.details is not None
    assert error.value.details["image_index"] == 2


def test_exif_orientation_is_applied() -> None:
    """Phones store portrait frames rotated with a correction tag. A 90-degree-off
    face fails the pose gate for a reason the user cannot act on.
    """
    image = Image.new("RGB", (200, 100), (0, 0, 0))
    buffer = io.BytesIO()
    exif = image.getexif()
    exif[274] = 6  # rotate 90 CW on display
    image.save(buffer, format="JPEG", exif=exif)

    array = decode_image(buffer.getvalue())

    # 200x100 landscape, tagged for rotation, must come back 100x200 portrait.
    assert array.shape[:2] == (200, 100)


def test_synthetic_frames_pass_through_the_decoder_untouched() -> None:
    """They are a header, not an encoded image — and no real format starts with
    those eight bytes, so a caller cannot produce one by accident.
    """
    payload = synthetic_image(3, quality=0.8)
    array = decode_image(payload)

    assert array.tobytes() == payload
