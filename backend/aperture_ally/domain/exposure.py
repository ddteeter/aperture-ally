"""Deterministic exposure-equivalence helper.

    new_duration = old_duration * (new_f / old_f)^2 * (old_ISO / new_ISO)

It only *calculates equivalence* under unchanged continuous illumination with known, manually set
controls. It does not judge whether the resulting shutter speed is suitable (hand-holding, subject
motion); the caller presents it as a starting point.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel

# Standard 1/3-stop shutter series (seconds), 1/8000 .. 60 s.
_SHUTTER_FRACTIONS = [
    8000, 6400, 5000, 4000, 3200, 2500, 2000, 1600, 1250, 1000, 800, 640, 500, 400, 320, 250, 200, 160,
    125, 100, 80, 60, 50, 40, 30, 25, 20, 15, 13, 10, 8, 6, 5, 4, 3,
]
_SHUTTER_LONG = [0.4, 0.5, 0.6, 0.8, 1, 1.3, 1.6, 2, 2.5, 3.2, 4, 5, 6, 8, 10, 13, 15, 20, 25, 30, 40, 50, 60]
STANDARD_SHUTTERS: list[float] = sorted([1 / d for d in _SHUTTER_FRACTIONS] + _SHUTTER_LONG)


class ExposureContext(BaseModel):
    light: str = "unknown"
    exposure_mode: str = "unknown"
    iso_mode: str = "unknown"
    flash_fired: bool | None = None
    illumination_unchanged: bool = True


class ExposureEquivalence(BaseModel):
    applicable: bool
    reasons: list[str]
    old: dict[str, float | None]
    new_f_number: float | None = None
    new_iso: float | None = None
    exact_duration_s: float | None = None
    rounded_duration_s: float | None = None
    rounded_label: str | None = None
    stops_change: float | None = None
    note: str | None = None


def format_shutter(seconds: float) -> str:
    if seconds >= 0.4:
        return f"{seconds:g} s"
    return f"1/{round(1 / seconds)} s"


def round_to_standard(seconds: float) -> float:
    return min(STANDARD_SHUTTERS, key=lambda s: abs(math.log2(s) - math.log2(seconds)))


def equivalent_exposure(
    old_duration_s: float | None,
    old_f_number: float | None,
    old_iso: float | None,
    new_f_number: float | None = None,
    new_iso: float | None = None,
    ctx: ExposureContext | None = None,
) -> ExposureEquivalence:
    ctx = ctx or ExposureContext()
    reasons: list[str] = []
    old = {"duration_s": old_duration_s, "f_number": old_f_number, "iso": old_iso}
    if not old_duration_s or not old_f_number or not old_iso:
        reasons.append("previous shutter, aperture and ISO are not all known from metadata")
    if ctx.light != "continuous":
        reasons.append(f"light is '{ctx.light}', equivalence needs unchanged continuous light")
    if ctx.flash_fired:
        reasons.append("flash fired; flash exposure does not follow shutter equivalence")
    if ctx.exposure_mode != "manual":
        reasons.append(f"exposure mode is '{ctx.exposure_mode}', not confirmed manual")
    if ctx.iso_mode != "manual":
        reasons.append(f"ISO mode is '{ctx.iso_mode}', not confirmed manual (auto ISO would compensate)")
    if not ctx.illumination_unchanged:
        reasons.append("illumination changed between shots")
    if new_f_number is None and new_iso is None:
        reasons.append("no aperture or ISO change requested")
    if reasons:
        return ExposureEquivalence(applicable=False, reasons=reasons, old=old, new_f_number=new_f_number, new_iso=new_iso)

    assert old_duration_s and old_f_number and old_iso
    nf = new_f_number or old_f_number
    ni = new_iso or old_iso
    exact = old_duration_s * (nf / old_f_number) ** 2 * (old_iso / ni)
    rounded = round_to_standard(exact)
    return ExposureEquivalence(
        applicable=True,
        reasons=[],
        old=old,
        new_f_number=nf,
        new_iso=ni,
        exact_duration_s=exact,
        rounded_duration_s=rounded,
        rounded_label=format_shutter(rounded),
        stops_change=round(math.log2(exact / old_duration_s), 2),
        note=(
            f"Starting point: {format_shutter(rounded)} at f/{nf:g}, ISO {ni:g} keeps the same exposure "
            "if the light is unchanged. Check the result; this does not judge motion blur or shake."
        ),
    )


def exposure_note_for(action: dict[str, Any] | None, exif: dict[str, Any], ctx: ExposureContext) -> dict | None:
    if not action or not action.get("exposure_target"):
        return None
    target = action["exposure_target"]
    eq = equivalent_exposure(
        exif.get("exposure_time_s"), exif.get("f_number"), exif.get("iso"),
        target.get("f_number"), target.get("iso"), ctx,
    )
    return eq.model_dump()


def _is_manual(exif: dict[str, Any]) -> bool:
    return exif.get("exposure_program") == "manual" or exif.get("exposure_mode_manual") is True


def exif_ev_delta(before: dict[str, Any], after: dict[str, Any]) -> tuple[float | None, str]:
    """Exposure change in stops between two photos from their EXIF settings (positive = brighter).

    Only meaningful when both were shot in manual exposure without flash: otherwise the camera may have
    compensated, and the settings say nothing about how bright the photo came out. Returns (delta, note);
    the note explains a ``None`` delta, or states the assumption behind a number.
    """
    for label, exif in (("the earlier photo", before), ("this photo", after)):
        if not all(exif.get(k) for k in ("exposure_time_s", "f_number", "iso")):
            return None, f"Shutter, aperture and ISO are not all in the metadata of {label}."
    for label, exif in (("the earlier photo", before), ("this photo", after)):
        if not _is_manual(exif):
            mode = exif.get("exposure_program") or "unknown"
            return None, (f"{label.capitalize()} was not shot in manual exposure ({mode.replace('_', ' ')}), "
                          "so the camera may have compensated; compare brightness from the histogram instead.")
    if before.get("flash_fired") or after.get("flash_fired"):
        return None, "Flash fired, and flash output is not part of the shutter/aperture/ISO settings."

    def exposure(e: dict[str, Any]) -> float:
        return float(e["exposure_time_s"]) * float(e["iso"]) / float(e["f_number"]) ** 2

    delta = round(math.log2(exposure(after) / exposure(before)), 2) + 0.0
    return delta, "From shutter, aperture and ISO in the metadata; assumes the light did not change."
