"""`aperture-ally inspect FILE…` — what the app can learn from your camera's files, safe to paste back.

For each file: decode check and timing, normalized metadata (what coaching uses), the camera tags that
matter for future features (focus/AF point, stabilisation, drive mode, lens, orientation, colour space),
RAW decode + preview path, and evidence build timing at full resolution. Privacy: serial numbers,
GPS, owner/artist/copyright and similar identifying tags are removed from all output.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from pathlib import Path
from typing import Any

INTERESTING = re.compile(
    r"(AF|Focus|Stabili|Drive|Lens|Orientation|ColorSpace|Colorspace|Quality|ImageSize|ImageWidth|ImageHeight|"
    r"Exposure|FNumber|ISO|Flash|WhiteBalance|Metering|Program|FocalLength|Model|Make|Software|Firmware|"
    r"PreviewImage|ThumbnailImage|SubjectDistance|FocusDistance)", re.IGNORECASE)
PRIVATE = re.compile(r"(Serial|GPS|Owner|Artist|Copyright|Author|Creator|UniqueID|ImageUniqueID|InternalSerial|"
                     r"BodySerial|LensSerial|CameraID|UserComment|Location|City|Country)", re.IGNORECASE)


def scrub(tags: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in tags.items() if not PRIVATE.search(k)}


def inspect_file(path: Path, all_tags: bool = False) -> dict[str, Any]:
    from .domain.models import Region
    from .imaging import raw as rawmod
    from .imaging.evidence import build_evidence, verify_decodable
    from .imaging.metadata import MetadataReader

    out: dict[str, Any] = {"file": path.name, "bytes": path.stat().st_size, "kind": "raw" if rawmod.is_raw(path) else "image"}
    reader = MetadataReader()
    try:
        t0 = time.perf_counter()
        meta = reader.read(path, include_raw=True)
        out["metadata_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        raw_tags = scrub(meta.pop("_raw", {}) or {})
        out["metadata_source"] = meta.get("source")
        out["normalized"] = scrub(meta)
        out["camera_tags"] = {k: v for k, v in raw_tags.items() if INTERESTING.search(k)}
        out["tag_count"] = len(raw_tags)
        if all_tags:
            out["all_tags"] = raw_tags
    finally:
        reader.close()

    image_for_evidence: Path | None = None
    tmp = Path(tempfile.mkdtemp(prefix="aperture-ally-inspect-"))
    if out["kind"] == "raw":
        try:
            import rawpy

            with rawpy.imread(str(path)) as r:
                out["raw"] = {"sizes": {k: getattr(r.sizes, k) for k in ("raw_width", "raw_height", "width", "height")},
                              "color_desc": r.color_desc.decode(errors="ignore")}
                try:
                    th = r.extract_thumb()
                    out["raw"]["embedded_preview"] = {"format": str(th.format), "bytes": len(th.data)}
                except Exception as exc:
                    out["raw"]["embedded_preview"] = f"none ({exc})"
            t0 = time.perf_counter()
            kind = rawmod.make_preview(path, tmp / "preview.jpg")
            out["raw"]["preview_used"] = kind
            out["raw"]["preview_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            image_for_evidence = tmp / "preview.jpg"
        except Exception as exc:
            out["raw"] = {"error": f"{type(exc).__name__}: {exc}"}
    else:
        try:
            t0 = time.perf_counter()
            w, h = verify_decodable(path)
            out["decode"] = {"width": w, "height": h, "ms": round((time.perf_counter() - t0) * 1000, 1)}
            image_for_evidence = path
        except Exception as exc:
            out["decode"] = {"error": str(exc)}
    if image_for_evidence:
        t0 = time.perf_counter()
        ev = build_evidence(image_for_evidence, tmp / "ev", [Region(id="r1", label="centre", x=0.35, y=0.35, w=0.3, h=0.3)])
        out["evidence"] = {"total_ms": round((time.perf_counter() - t0) * 1000, 1), "stages_ms": ev["timings"],
                           "oriented_size": [ev["width"], ev["height"]],
                           "color": {k: v for k, v in ev["measurements"]["image"].items() if k not in ("width", "height")},
                           "global_clip": ev["measurements"]["global"]["highlight_clip_fraction"]}
    return out


def main(paths: list[str], all_tags: bool = False, out_file: str | None = None) -> int:
    import platform
    import shutil

    results = {"host": {"platform": platform.platform(), "machine": platform.machine(),
                        "exiftool": shutil.which("exiftool") is not None},
               "files": [inspect_file(Path(p).expanduser(), all_tags) for p in paths]}
    text = json.dumps(results, indent=2, default=str)
    if out_file:
        Path(out_file).write_text(text)
        print(f"wrote {out_file} (identifying tags removed; review before sharing)")
    else:
        print(text)
    return 0
