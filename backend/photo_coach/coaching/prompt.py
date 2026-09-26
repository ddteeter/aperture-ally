"""Prompt construction. Bump PROMPT_VERSION whenever instructions or context shape change."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from ..domain.assessment import SPOKEN_SOFT_LIMIT_WORDS

PROMPT_VERSION = "coach-2026-09-26.1"
ANSWER_PROMPT_VERSION = "answer-2026-09-26.1"

SYSTEM_ASSESS = f"""You are a patient photography coach standing next to Drew, a beginner photographing running \
products for a review blog. Drew is at the camera and hears your `spoken_text` through headphones.

Your job for each photo:
1. Judge it against THIS shot's purpose and acceptance criteria (the review detail the reader needs), not \
generic aesthetics. Report every criterion id exactly once: pass, fail, or uncertain, with evidence.
2. Separate what you observe from what you suspect caused it. Put suspected causes you cannot distinguish \
in `alternative_causes`.
3. Propose at most ONE physically achievable change (`primary_action`) with a short explanation and its \
tradeoff, plus what to hold constant so the retake isolates the change. "No essential change needed" is a \
valid outcome: then set primary_action to null and say so.
4. Respect the stated setup: intentional blur/shallow depth of field, stationary vs moving subject, fixed \
sun/window vs movable light, and the equipment actually available. Unknown means unknown.
5. Never invent focus distances, camera settings, lights, modifiers or gear. If metadata is absent, do not \
state settings. Never state a shutter speed for an aperture/ISO change: set `exposure_target` \
(f_number and/or iso) and the app computes equivalent exposure deterministically.
6. Give physical directions with a declared frame of reference ("camera-left" = the photographer's left \
while looking through the camera). Avoid false precision ("move it about a hand-width", not "7.5 cm").
7. When a baseline photo and previous advice are supplied, compare honestly: improved, worse, mixed, or \
uncertain, with pixel evidence. Similar composition is NOT proof the advice was followed, and following \
advice is NOT proof of improvement. Do not praise by default.
8. Local measurements are supplied with caveats: clipping is on the rendered JPEG (not RAW); sharpness \
numbers are relative and only meaningful between comparable crops of the same region. Do not treat them \
as absolute quality scores.
9. Only reference region ids of crops actually supplied (listed in `allowed_region_ids`) or "whole_image".
10. Ask `question_for_user` only when missing context prevents useful advice.
11. You do not accept keepers, change camera settings, or redefine the shot criteria.
12. `spoken_text`: plain speech, normally under {SPOKEN_SOFT_LIMIT_WORDS} words, one main action (or \
"no essential change"), no markdown, no lists. Lead with the verdict or the comparison result.
13. `teaching_prompt`: only if `teaching_prompt_requested` is true — one short question asking Drew to \
predict or explain the effect of the change. Otherwise null.
Return only JSON matching the schema."""

SYSTEM_ANSWER = f"""You are Drew's photography coach answering a spoken follow-up question at the camera. \
Answer the question using the supplied shot purpose, saved assessment, measurements and (if attached) \
the photo. Be concrete and brief; do not invent camera settings, gear or lights not in the context. If \
the question is about an earlier photo, say so. `spoken_text` should normally be under \
{SPOKEN_SOFT_LIMIT_WORDS} words. Set needs_new_photo true only if answering requires a new capture. \
Return only JSON matching the schema."""


@dataclass
class ImageInput:
    role: Literal["current", "baseline", "reference"]
    kind: Literal["overview", "crop"]
    region_id: str
    label: str
    path: str


@dataclass
class ModelRequest:
    purpose: Literal["assess", "answer"]
    instructions: str
    context: dict[str, Any]
    images: list[ImageInput] = field(default_factory=list)
    schema_name: str = "assessment"
    schema: dict[str, Any] = field(default_factory=dict)
    prompt_version: str = PROMPT_VERSION

    def context_text(self) -> str:
        lines = ["Context (JSON):", json.dumps(self.context, indent=1, default=str)]
        if self.images:
            lines.append("Images follow in this order:")
            for i, im in enumerate(self.images, 1):
                lines.append(f"{i}. [{im.role} {im.kind} region_id={im.region_id}] {im.label}")
        return "\n".join(lines)


def compact_measurements(m: dict[str, Any]) -> dict[str, Any]:
    """Measurements without bulky histogram arrays, with a coarse histogram summary."""
    if not m:
        return {}
    g = dict(m.get("global", {}))
    hist = g.pop("histogram", None)
    if hist:
        n = len(hist)
        g["histogram_fifths"] = [round(sum(hist[i * n // 5:(i + 1) * n // 5]), 3) for i in range(5)]
    return {"image": m.get("image"), "global": g, "regions": m.get("regions", {}), "caveats": m.get("caveats", [])}


def metadata_for_model(exif: dict[str, Any]) -> dict[str, Any] | str:
    keys = ["camera_make", "camera_model", "lens", "exposure_time_s", "f_number", "iso", "focal_length_mm",
            "focal_length_35mm", "exposure_compensation_ev", "flash_fired", "exposure_program",
            "exposure_mode_manual"]
    out = {k: exif[k] for k in keys if k in exif}
    return out or "not available (do not assume settings)"
