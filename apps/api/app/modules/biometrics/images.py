"""Decoding and validating caller-supplied images.

This is a trust boundary. Everything here runs on bytes an unauthenticated-ish
caller chose, before any of it reaches a model, so the checks are cheap, ordered
cheapest-first, and fail closed.

Three attacks are specifically in scope:

* **Oversized payloads** — rejected on the encoded length, before base64 even
  expands them.
* **Decompression bombs** — a 40 KB PNG can declare 100,000 x 100,000 pixels and
  allocate 30 GB on decode. Pillow's own guard is a warning by default; this
  module reads the header first and refuses on declared dimensions, so nothing
  is ever allocated.
* **Non-images** — a `.jpg` that is actually a zip, or truncated data that
  decodes to garbage.

Pillow rather than OpenCV: decoding must work under `FACE_ENGINE=fake`, and
OpenCV lives in the optional `face` extra. Colour order is BGR because that is
what InsightFace's preprocessing assumes; getting it backwards does not error,
it silently degrades accuracy.
"""

from __future__ import annotations

import base64
import binascii
import io

import numpy as np
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.core.exceptions import BadRequestError, PayloadTooLargeError

# Beyond this, a frame carries no extra usable detail for a 112 px alignment —
# it only costs memory and detection time. 8K is already far past useful.
MAX_DIMENSION = 8192
# The largest sensible enrolment frame, as a pixel count. 4096x4096.
MAX_PIXELS = 16_777_216
MIN_DIMENSION = 64

# Magic bytes of the synthetic frames FakeFaceEngine understands. Kept here as a
# literal rather than imported so this module has no dependency on the fake
# engine — the two only need to agree on eight bytes.
_FAKE_MAGIC = b"FVASFAKE"

_DATA_URL_PREFIX = "data:"


def _strip_data_url(payload: str) -> str:
    """Accept a bare base64 string or a full `data:image/jpeg;base64,...` URL.

    Browsers produce the latter from `canvas.toDataURL()`, and requiring
    integrators to strip it is a pointless source of support tickets.
    """
    if not payload.startswith(_DATA_URL_PREFIX):
        return payload
    _, separator, encoded = payload.partition(",")
    if not separator:
        raise BadRequestError(
            "The image data URL is malformed.",
            code="invalid_image",
        )
    return encoded


def decode_base64(payload: str, *, index: int | None = None) -> bytes:
    """Base64 to raw bytes, with the size check applied before decoding."""
    encoded = _strip_data_url(payload.strip())

    # Base64 inflates by 4/3. Checking the encoded length first means an
    # oversized payload never gets expanded in memory.
    limit_bytes = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024
    if len(encoded) * 3 // 4 > limit_bytes:
        raise PayloadTooLargeError(
            f"Image exceeds the {settings.MAX_IMAGE_SIZE_MB} MB limit.",
            details=_with_index({"limit_mb": settings.MAX_IMAGE_SIZE_MB}, index),
        )

    try:
        # validate=False: tolerate whitespace and newlines, which several HTTP
        # clients insert into long base64 fields.
        raw = base64.b64decode(encoded, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise BadRequestError(
            "The image is not valid base64.",
            code="invalid_image",
            details=_with_index({}, index),
        ) from exc

    if not raw:
        raise BadRequestError(
            "The image is empty.",
            code="invalid_image",
            details=_with_index({}, index),
        )
    return raw


def decode_image(raw: bytes, *, index: int | None = None) -> NDArray[np.uint8]:
    """Raw bytes to an HxWx3 BGR array.

    Synthetic test frames pass through untouched: they are not encoded images,
    they are a header the fake engine reads. Real callers can never produce them
    by accident — no image format begins with those eight bytes.
    """
    if raw.startswith(_FAKE_MAGIC):
        return np.frombuffer(raw, dtype=np.uint8)

    try:
        # Two passes. The first only parses the header, so `image.size` is known
        # before a single pixel is allocated — that is what makes the bomb check
        # a refusal rather than an out-of-memory kill.
        with Image.open(io.BytesIO(raw)) as probe:
            width, height = probe.size
            _assert_sane_dimensions(width, height, index=index)

        with Image.open(io.BytesIO(raw)) as image:
            # EXIF orientation matters: phones store portrait frames rotated
            # with a correction tag, and a 90-degree-off face fails the pose
            # gate for a reason the user cannot act on.
            from PIL import ImageOps

            corrected = ImageOps.exif_transpose(image) or image
            rgb = corrected.convert("RGB")
            array = np.asarray(rgb, dtype=np.uint8)
    except UnidentifiedImageError as exc:
        raise BadRequestError(
            "The image could not be decoded. Supported formats: JPEG, PNG, WebP.",
            code="invalid_image",
            details=_with_index({}, index),
        ) from exc
    except (OSError, ValueError) as exc:
        # Truncated files land here rather than in UnidentifiedImageError.
        raise BadRequestError(
            "The image is corrupt or truncated.",
            code="invalid_image",
            details=_with_index({}, index),
        ) from exc

    # RGB to BGR. InsightFace's preprocessing was trained on OpenCV's channel
    # order; swapping it does not raise, it just quietly costs accuracy.
    bgr: NDArray[np.uint8] = np.ascontiguousarray(array[:, :, ::-1])
    return bgr


def _assert_sane_dimensions(width: int, height: int, *, index: int | None) -> None:
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        raise BadRequestError(
            f"The image is too small ({width}x{height}). Minimum {MIN_DIMENSION}x{MIN_DIMENSION}.",
            code="invalid_image",
            details=_with_index({"width": width, "height": height}, index),
        )
    if width > MAX_DIMENSION or height > MAX_DIMENSION or width * height > MAX_PIXELS:
        raise PayloadTooLargeError(
            f"The image is too large ({width}x{height}).",
            details=_with_index(
                {"width": width, "height": height, "max_pixels": MAX_PIXELS}, index
            ),
        )


def _with_index(details: dict[str, object], index: int | None) -> dict[str, object]:
    """Tag the failure with which frame caused it.

    A capture UI submitting five frames needs to know which one to retake; an
    error that says only "an image was invalid" forces it to discard all five.
    """
    if index is not None:
        details["image_index"] = index
    return details


def load_images(payloads: list[str]) -> list[NDArray[np.uint8]]:
    """Decode every frame, reporting the index of the first bad one."""
    return [
        decode_image(decode_base64(payload, index=i), index=i) for i, payload in enumerate(payloads)
    ]
