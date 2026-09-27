"""Measured before/after numbers for a retake, and framing-based hints (baseline picks, shot attribution).

Everything here is computed from stored evidence (measurements + overview images); no model call.
Framing scores come from ``imaging.framing`` and are cached there per image pair.
"""

from __future__ import annotations

from typing import Any

from .domain.exposure import exif_ev_delta
from .domain.models import Capture, ShotRequirement
from .imaging.framing import COMPARABLE, framing_between, framing_detail

_FLAT = 0.01  # laplacian variance at/below this: nothing to measure sharpness on
_ATTRIBUTION_LOOKBACK = 6  # newest captures per shot considered when guessing where a photo belongs
_MATCH_FLOOR = 0.2  # below this a "best match" is no evidence at all: report no matched photo
# Recovered photos (no shot switch recorded) are moved to another shot only on strong evidence. Fabric
# close-ups match on texture alone, and several shots can share one fabric, so a texture-only match has to
# be near-certain and clearly better than the photo's own shot.
_TEXTURE_HINT, _TEXTURE_MARGIN = 0.85, 0.15


def region_labels(ev: dict[str, Any]) -> dict[str, str]:
    return {x["id"]: ("auto-picked detail area" if x.get("source") == "auto" else x.get("label") or x["id"])
            for x in ev.get("crops", [])}


def _sharpness_change_pct(before: dict[str, Any], after: dict[str, Any]) -> float | None:
    b, a = before.get("laplacian_var"), after.get("laplacian_var")
    if b is None or a is None or b <= _FLAT or a <= _FLAT:
        return None
    return round((a / b - 1) * 100, 1)


def scope_delta(scope: str, label: str, before: dict[str, Any], after: dict[str, Any], *,
                sharpness: bool) -> dict[str, Any]:
    return {
        "scope": scope,
        "label": label,
        "sharpness_change_pct": _sharpness_change_pct(before, after) if sharpness else None,
        "mean_before": before.get("mean_luminance"),
        "mean_after": after.get("mean_luminance"),
        "highlight_clip_before": before.get("highlight_clip_fraction", 0.0),
        "highlight_clip_after": after.get("highlight_clip_fraction", 0.0),
        "shadow_clip_before": before.get("shadow_clip_fraction", 0.0),
        "shadow_clip_after": after.get("shadow_clip_fraction", 0.0),
        "histogram_before": before.get("histogram"),
        "histogram_after": after.get("histogram"),
    }


def comparison_metrics(cap: Capture, base: Capture | None) -> dict[str, Any] | None:
    """Numbers for "what the retake changed" against ``cap``'s baseline (None without measurements).

    Regions are compared only when both photos measured the same rectangle: an auto-picked detail area
    that landed elsewhere is a different patch of the photo, not a before/after.
    """
    if base is None:
        return None
    mb, ma = base.evidence.get("measurements"), cap.evidence.get("measurements")
    if not mb or not ma:
        return None
    labels = region_labels(cap.evidence)
    regions = []
    for rid, after in (ma.get("regions") or {}).items():
        before = (mb.get("regions") or {}).get(rid)
        if not before or before.get("rect") != after.get("rect"):
            continue
        regions.append(scope_delta(rid, labels.get(rid, rid), before, after, sharpness=True))
    glob = None
    if mb.get("global") and ma.get("global"):
        glob = scope_delta("global", "whole frame", mb["global"], ma["global"], sharpness=False)
    ev, note = exif_ev_delta(base.exif, cap.exif)
    return {
        "baseline_capture_id": base.id,
        "baseline_seq": base.seq,
        "framing": framing_between(base.evidence, cap.evidence),
        "ev_delta": ev,
        "ev_note": note,
        "regions": regions,
        "global": glob,
    }


def attribution_hint(cap: Capture, caps: list[Capture], shots: dict[str, ShotRequirement]) -> dict[str, Any] | None:
    """For a photo taken right after a shot switch (or found at startup): the other shot it may belong to.

    The candidate is the shot that was active before the switch; for recovered photos (no switch
    recorded) it is the other shot whose recent photos match this framing best, if any match well.
    """
    if not cap.attribution_ambiguous or not cap.evidence.get("overview"):
        return None
    ctx = cap.attribution_context or {}
    previous = ctx.get("previous_shot_id")
    if previous and previous != cap.shot_id and previous in shots:
        candidates = [previous]
    else:
        previous = None
        candidates = [sid for sid in shots if sid != cap.shot_id]
    best: tuple[float, str, int, str] | None = None
    per_shot: dict[str, tuple[float, int]] = {}
    for sid in candidates:
        others = [c for c in caps if c.shot_id == sid and c.id != cap.id and c.evidence.get("overview")]
        for other in others[-_ATTRIBUTION_LOOKBACK:]:
            m = framing_detail(other.evidence, cap.evidence)
            if m is None:
                continue
            if sid not in per_shot or m.score > per_shot[sid][0]:
                per_shot[sid] = (m.score, other.seq)
            if best is None or m.score > best[0]:
                best = (m.score, sid, other.seq, m.basis)
    if previous:
        shot_id = previous
    elif best and _convincing(best[0], best[3], _best_in_shot(cap, caps, cap.shot_id)):
        shot_id = best[1]
    else:
        return None
    score, seq = per_shot.get(shot_id, (None, None))
    if score is not None and score < _MATCH_FLOOR:
        score, seq = None, None
    return {
        "shot_id": shot_id,
        "shot_title": shots[shot_id].title,
        "matched_capture_seq": seq,
        "framing_score": score,
        "seconds_after_switch": ctx.get("seconds_after_switch") if previous else None,
    }


def _convincing(score: float, basis: str, own_best: float) -> bool:
    if basis == "texture":
        return score >= max(COMPARABLE, _TEXTURE_HINT) and score >= own_best + _TEXTURE_MARGIN
    return score >= COMPARABLE and score > own_best


def _best_in_shot(cap: Capture, caps: list[Capture], shot_id: str | None) -> float:
    if shot_id is None:
        return 0.0
    own = [c for c in caps if c.shot_id == shot_id and c.id != cap.id and c.evidence.get("overview")]
    scores = [f["score"] for c in own[-_ATTRIBUTION_LOOKBACK:]
              for f in [framing_between(c.evidence, cap.evidence)] if f]
    return max(scores, default=0.0)


def baseline_candidates(cap: Capture, caps: list[Capture], verdicts: dict[str, str | None],
                        limit: int = 8) -> list[dict[str, Any]]:
    """Earlier photos of the same shot, newest first, with their verdict and framing match to ``cap``."""
    if not cap.shot_id:
        return []
    earlier = sorted((c for c in caps if c.shot_id == cap.shot_id and c.seq < cap.seq), key=lambda c: -c.seq)
    return [{
        "capture_id": c.id,
        "seq": c.seq,
        "verdict": verdicts.get(c.id),
        "framing": framing_between(c.evidence, cap.evidence),
        "is_current_baseline": c.id == cap.baseline_capture_id,
    } for c in earlier[:limit]]
