"""Plain-language histogram reading, computed by fixed rules (instant, consistent, no model call).

Input is the measurement dict produced by ``evidence.build_evidence``. Output is written for a
beginner: what the graph shows, whether it matters for *this* photo, and where to look. There is no
"correct" histogram shape; the rules only flag lost detail (clipping) and flat or extreme tonality, and
say when a lean is probably fine. Everything describes the rendered JPEG, not the RAW file.
"""

from __future__ import annotations

from typing import Any

SHADOW_END, HIGHLIGHT_START = 64, 192  # of 0..255: bottom quarter / top quarter
CLIP_PROBLEM, CLIP_WARN = 0.02, 0.002  # fraction of pixels at pure white/black

HOW_TO_READ = [
    "Left to right is dark to bright: black on the far left, white on the far right.",
    "The height at each point is how much of the photo has that brightness. Tall on the left means lots of dark "
    "areas; tall on the right means lots of bright areas.",
    "There is no correct shape. A white shirt on a white background should lean right; a black shoe should lean left.",
    "What matters is the edges. A spike pressed against the right wall means pure white with no detail left "
    "(blown highlights); against the left wall, pure black (crushed shadows).",
    "Check the graph for the part you care about (your marked regions) before the whole frame.",
    "This describes the processed JPEG. The RAW file may hold a little more detail at the edges.",
]


def _zones(hist: list[float]) -> dict[str, float]:
    n = len(hist)
    s_end, h_start = n * SHADOW_END // 256, n * HIGHLIGHT_START // 256
    return {"shadows": sum(hist[:s_end]), "midtones": sum(hist[s_end:h_start]), "highlights": sum(hist[h_start:])}


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%" if x < 0.1 else f"{x * 100:.0f}%"


def _shape_headline(z: dict[str, float], mean: float | None, spread: float | None) -> tuple[str, str]:
    if mean is not None and mean < 55:
        return "Very dark overall", "very_dark"
    if mean is not None and mean > 205:
        return "Very bright overall", "very_bright"
    if z["shadows"] > 0.25 and z["highlights"] > 0.25:
        return "Wide range: both deep shadows and bright highlights", "contrast"
    if spread is not None and spread < 100:
        return "Flat: most tones bunched together (can look dull or hazy)", "flat"
    top = max(z, key=z.get)  # type: ignore[arg-type]
    return {"shadows": "Mostly dark", "midtones": "Mostly mid-tones", "highlights": "Mostly bright"}[top], top


def describe(stats: dict[str, Any], name: str, *, is_region: bool) -> dict[str, Any]:
    hist = stats.get("histogram") or []
    z = _zones(hist) if hist else {}
    spread = None
    if stats.get("p99_luminance") is not None and stats.get("p01_luminance") is not None:
        spread = stats["p99_luminance"] - stats["p01_luminance"]
    shape, shape_key = _shape_headline(z, stats.get("mean_luminance"), spread) if z else ("", "")
    hi, lo = stats.get("highlight_clip_fraction", 0) or 0, stats.get("shadow_clip_fraction", 0) or 0
    findings: list[dict[str, Any]] = []

    def add(severity: str, zone: str, headline: str, detail: str) -> None:
        findings.append({"scope": name, "severity": severity, "zone": zone, "headline": headline, "detail": detail})

    where = f"the {name}" if is_region else "the frame"
    if hi >= CLIP_PROBLEM:
        add("problem" if is_region else "warn", "clip_high", f"{_pct(hi)} of {where} is pure white",
            "Detail is gone there: texture, weave or print in those spots can't be recovered from the JPEG. "
            "Usually glare or too much exposure: change the light angle, diffuse it, or expose a little darker.")
    elif hi >= CLIP_WARN:
        add("info", "clip_high", f"A few pure-white spots in {where} ({_pct(hi)})",
            "Small specular highlights (shiny points) are normal. Only a problem if they sit on something the "
            "reader needs to see.")
    if lo >= CLIP_PROBLEM:
        add("problem" if is_region else "warn", "clip_low", f"{_pct(lo)} of {where} is pure black",
            "Shadow detail is gone there. Add light to the shadow side (reflector, second light) or expose brighter.")
    elif lo >= CLIP_WARN:
        add("info", "clip_low", f"A few pure-black spots in {where} ({_pct(lo)})",
            "Deep shadows in creases or behind the product are fine unless they hide a feature.")
    if shape_key == "very_dark":
        add("warn", "shadows", f"{where.capitalize()} is very dark",
            "Most tones sit on the left. Details you need may look murky: add light or expose brighter, "
            "unless the product itself is black.")
    if shape_key == "very_bright":
        add("warn", "highlights", f"{where.capitalize()} is very bright",
            "Most tones sit on the right. Watch for lost texture: reduce light or expose darker, "
            "unless the product itself is white.")
    if shape_key == "flat":
        add("info", "midtones", "Low contrast", "Tones are bunched in the middle. Harder, more directional light "
            "or a darker background can add depth, if the photo looks dull.")
    if shape_key == "highlights" and hi < CLIP_WARN:
        add("info", "highlights", "Leans bright, but nothing is blown",
            "That's fine for a light-coloured product or background. Keep an eye on the right edge.")
    if shape_key == "shadows" and lo < CLIP_WARN and not is_region:
        add("info", "shadows", "Leans dark, but nothing is crushed",
            "Fine for a dark product or moody look; brighten if the details you need look murky.")
    if not findings:
        add("ok", "midtones", f"No lost detail in {where}", "Nothing is pure white or pure black. Tones are recoverable.")
    severity = next((s for s in ("problem", "warn", "info", "ok") if any(f["severity"] == s for f in findings)), "ok")
    headline = findings[0]["headline"] if severity in ("problem", "warn") else shape or findings[0]["headline"]
    return {"scope": name, "headline": headline, "shape": shape, "severity": severity,
            "zones": {k: round(v, 3) for k, v in z.items()}, "highlight_clip": hi, "shadow_clip": lo,
            "findings": findings}


def interpret(measurements: dict[str, Any], region_labels: dict[str, str] | None = None) -> dict[str, Any]:
    """Whole-frame and per-region reading. Regions come first: they are what the shot is about."""
    labels = region_labels or {}
    regions = [
        describe(stats, labels.get(rid) or f"region {rid}", is_region=True) | {"region_id": rid}
        for rid, stats in (measurements.get("regions") or {}).items()
    ]
    overall = describe(measurements.get("global") or {}, "whole frame", is_region=False)
    worst = next((r for r in regions if r["severity"] == "problem"), None)
    summary = worst["headline"] if worst else (overall["headline"] if overall["severity"] in ("warn", "problem")
                                              else overall["shape"] or overall["headline"])
    return {"summary": summary, "regions": regions, "overall": overall, "how_to_read": HOW_TO_READ,
            "caveat": "Measured on the processed JPEG, not the RAW file."}


def compare(before: dict[str, Any], after: dict[str, Any], labels: dict[str, str] | None = None) -> list[str]:
    """Sentences describing what a retake changed, per shared region, then the whole frame."""
    out: list[str] = []
    pairs = [(rid, (before.get("regions") or {}).get(rid), stats) for rid, stats in (after.get("regions") or {}).items()]
    pairs.append(("whole frame", before.get("global"), after.get("global")))
    for name, b, a in pairs:
        if not b or not a:
            continue
        label = name if name == "whole frame" else (f"the {labels[name]}" if labels and name in labels else f"region {name}")
        for key, what in (("highlight_clip_fraction", "pure white"), ("shadow_clip_fraction", "pure black")):
            x, y = b.get(key, 0) or 0, a.get(key, 0) or 0
            if max(x, y) >= CLIP_WARN and abs(x - y) >= max(CLIP_WARN, 0.25 * max(x, y)):
                verb = "dropped" if y < x else "rose"
                out.append(f"{what.capitalize()} in {label} {verb} from {_pct(x)} to {_pct(y)}.")
        mb, ma = b.get("mean_luminance"), a.get("mean_luminance")
        if mb is not None and ma is not None and abs(ma - mb) >= 15:
            out.append(f"{label.capitalize()} got {'brighter' if ma > mb else 'darker'} overall "
                       f"({mb:.0f} → {ma:.0f} on a 0–255 scale).")
    return out
