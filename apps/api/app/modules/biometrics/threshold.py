"""Threshold policy and the decision rule.

The threshold is the product's central security/usability dial. Everything here
is a *measurement* from the Phase 0 calibration run — 8,559 genuine and 500,000
impostor LFW pairs, [docs/14-phase-0-spike.md](../../../../docs/14-phase-0-spike.md) —
not a preference. Changing a number in this file without re-running that
calibration makes the FAR/FRR figures shown in the console into lies.

Two rules here are security properties rather than conveniences:

* **A per-request threshold may only be stricter.** Allowing a request to loosen
  it would let a compromised API key silently weaken the posture the
  organization configured, from outside the console, without an audit entry.
* **A decision carries its threshold.** `threshold_applied` is denormalised onto
  every session row, so an auditor asking why something was verified in March
  gets March's threshold rather than today's configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

# Measured. `far` and `frr` are from the calibration run; `None` means the
# quantity is not resolvable at that dataset size and is deliberately not
# reported as a number.
#
# Strict measures the same FAR as Balanced because beyond ~0.35 the impostor
# tail falls below what 500,000 pairs can resolve. It stays available as
# defence-in-depth against a population harder than LFW, but its benefit is
# unmeasured — and the console says so rather than printing a reassuring zero.


@dataclass(frozen=True, slots=True)
class Preset:
    name: str
    threshold: Decimal
    far: float | None
    frr: float | None
    intent: str
    far_is_resolvable: bool = True


LENIENT: Final = Preset(
    name="lenient",
    threshold=Decimal("0.320"),
    far=1.0e-5,
    frr=0.0273,
    intent="High-volume, low-risk. Retail check-in, event entry.",
)

BALANCED: Final = Preset(
    name="balanced",
    threshold=Decimal("0.380"),
    far=8.0e-6,
    frr=0.0306,
    intent="The default. Suits most authentication flows.",
)

STRICT: Final = Preset(
    name="strict",
    threshold=Decimal("0.450"),
    far=8.0e-6,
    frr=0.0421,
    intent="Financial transactions, administrative access.",
    # The honest part: this FAR is identical to Balanced's because the
    # measurement floor was reached, not because the threshold does nothing.
    far_is_resolvable=False,
)

PRESETS: Final[dict[str, Preset]] = {preset.name: preset for preset in (LENIENT, BALANCED, STRICT)}

# Custom is bounded. Below 0.20 the false-accept rate stops being a rounding
# error; above 0.80 essentially nobody verifies and the customer has built an
# outage, not a security control.
CUSTOM_MIN: Final = Decimal("0.200")
CUSTOM_MAX: Final = Decimal("0.800")

# Confidence bands, as offsets above the applied threshold. A bare boolean
# throws away information the customer's risk engine can use: a `low` band on a
# $50,000 transfer is exactly where they should demand a second factor.
HIGH_BAND: Final = Decimal("0.15")
MEDIUM_BAND: Final = Decimal("0.05")


def resolve(
    *,
    configured: Decimal,
    requested: Decimal | None,
) -> Decimal:
    """The threshold this request will actually use.

    A request may tighten the organization's setting and may not loosen it.
    Returning the stricter of the two — rather than rejecting a looser request —
    is deliberate: the caller asked for a security level, they get at least it,
    and an integrator who misconfigures their client fails safe instead of
    getting a 400 on their login path.
    """
    if requested is None:
        return configured
    return max(configured, requested)


def confidence_for(similarity: Decimal, threshold: Decimal) -> str | None:
    """Band a verified result. `None` when the result is not verified.

    Bands are relative to the *applied* threshold, not to a fixed scale, because
    "how much margin did this decision have" is the question a risk engine is
    actually asking.
    """
    if similarity < threshold:
        return None
    margin = similarity - threshold
    if margin >= HIGH_BAND:
        return "high"
    if margin >= MEDIUM_BAND:
        return "medium"
    return "low"


def preset_for(threshold: Decimal) -> str:
    """Name the preset a threshold corresponds to, or `custom`."""
    for preset in PRESETS.values():
        if preset.threshold == threshold:
            return preset.name
    return "custom"


def describe(threshold: Decimal) -> dict[str, object]:
    """What the console shows next to the threshold slider.

    Returns the measured figures where they exist and says so where they do
    not. An interface that prints `FAR 0.0%` for an unmeasured configuration is
    worse than one that prints nothing.
    """
    name = preset_for(threshold)
    preset = PRESETS.get(name)
    if preset is None:
        return {
            "preset": "custom",
            "threshold": float(threshold),
            "far": None,
            "frr": None,
            "measured": False,
            "note": (
                "Custom thresholds are not calibrated. The published FAR/FRR figures "
                "apply to the presets only."
            ),
        }
    return {
        "preset": preset.name,
        "threshold": float(preset.threshold),
        "far": preset.far,
        "frr": preset.frr,
        "measured": preset.far_is_resolvable,
        "intent": preset.intent,
        "note": (
            None
            if preset.far_is_resolvable
            else (
                "This false-accept rate is identical to Balanced because 500,000 impostor "
                "pairs cannot resolve a lower one. Stricter matching is still defence in "
                "depth, but its benefit here is unmeasured rather than zero."
            )
        ),
    }
