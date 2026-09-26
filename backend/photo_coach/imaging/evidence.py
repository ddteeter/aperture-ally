"""Build model/UI evidence for a capture: overview, thumbnail, region crops, measurements.

Everything is orientation-normalized (EXIF transpose) before coordinates are applied, so a region
selected on the displayed overview maps to the same pixels in the full-resolution crop.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageCms, ImageOps

from ..domain.models import Region
from . import measurements as M

log = logging.getLogger(__name__)
Image.MAX_IMAGE_PIXELS = 200_000_000

_SRGB = ImageCms.createProfile("sRGB")


class DecodeError(Exception):
    pass


def verify_decodable(path: Path) -> tuple[int, int]:
    """Fully decode a JPEG/TIFF/PNG; raises DecodeError for truncated/partial files."""
    try:
        with Image.open(path) as im:
            im.load()
            return im.size
    except Exception as exc:
        raise DecodeError(str(exc)) from exc


def load_oriented_srgb(path: Path) -> tuple[Image.Image, dict[str, Any]]:
    info: dict[str, Any] = {}
    with Image.open(path) as im:
        im.load()
        info["orientation_tag"] = im.getexif().get(274)
        oriented = ImageOps.exif_transpose(im)
        icc = im.info.get("icc_profile")
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            desc = ImageCms.getProfileDescription(src).strip()
            info["icc_profile"] = desc
            if "srgb" not in desc.lower():
                oriented = ImageCms.profileToProfile(oriented.convert("RGB"), src, _SRGB, outputMode="RGB")
                info["color_converted"] = True
        except Exception as exc:
            info["icc_error"] = str(exc)
    else:
        info["icc_profile"] = None
        info["color_assumption"] = "no embedded ICC profile; treated as sRGB"
    return oriented.convert("RGB"), info


def _save_jpeg(img: Image.Image, path: Path, quality: int = 88) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    img.save(tmp, "JPEG", quality=quality, optimize=True)
    tmp.replace(path)


def build_evidence(
    image_path: Path,
    out_dir: Path,
    regions: list[Region],
    *,
    overview_long_edge: int = 1600,
    crop_max_edge: int = 1024,
    max_crops: int = 3,
) -> dict[str, Any]:
    img, color_info = load_oriented_srgb(image_path)
    W, H = img.size
    arr = np.asarray(img)

    scale = min(1.0, overview_long_edge / max(W, H))
    overview = img.resize((round(W * scale), round(H * scale)), Image.Resampling.LANCZOS) if scale < 1 else img
    _save_jpeg(overview, out_dir / "overview.jpg")
    thumb = img.copy()
    thumb.thumbnail((360, 360), Image.Resampling.LANCZOS)
    _save_jpeg(thumb, out_dir / "thumb.jpg", quality=80)

    crops: list[dict[str, Any]] = []
    selected = [r.clamp() for r in regions][:max_crops]
    auto = False
    if not selected:
        x, y, w, h = M.auto_detail_region(arr)
        selected = [Region(id="auto1", label="auto: highest local detail (not user-selected)", x=x, y=y, w=w, h=h)]
        auto = True

    region_metrics: dict[str, Any] = {}
    for r in selected:
        x0, y0 = int(r.x * W), int(r.y * H)
        x1, y1 = max(x0 + 1, int((r.x + r.w) * W)), max(y0 + 1, int((r.y + r.h) * H))
        sub = arr[y0:y1, x0:x1]
        crop = Image.fromarray(sub)
        cscale = min(1.0, crop_max_edge / max(crop.size))
        if cscale < 1:
            crop = crop.resize((round(crop.width * cscale), round(crop.height * cscale)), Image.Resampling.LANCZOS)
        cpath = out_dir / f"crop_{r.id}.jpg"
        _save_jpeg(crop, cpath, quality=92)
        rect = [round(r.x, 4), round(r.y, 4), round(r.w, 4), round(r.h, 4)]
        crops.append({
            "id": r.id, "label": r.label, "source": "auto" if auto else "user", "rect": rect,
            "px_rect": [x0, y0, x1, y1], "path": str(cpath), "scale": round(cscale, 4),
            "native_resolution": cscale == 1,
        })
        region_metrics[r.id] = {
            "rect": rect,
            "px_size": [x1 - x0, y1 - y0],
            **{k: v for k, v in M.tonal_stats(sub).items() if k != "histogram"},
            **M.sharpness(sub),  # at native resolution
        }

    measurements = {
        "image": {"width": W, "height": H, **color_info},
        "global": {**M.tonal_stats(M.subsample_nearest(arr)), **M.sharpness(np.asarray(overview))},
        "regions": region_metrics,
        "notes": {"global_sharpness_scale": "measured on overview", "region_sharpness_scale": "native pixels"},
        "caveats": M.CAVEATS,
    }
    return {
        "width": W,
        "height": H,
        "overview": {"path": str(out_dir / "overview.jpg"), "width": overview.width, "height": overview.height},
        "thumb": str(out_dir / "thumb.jpg"),
        "crops": crops,
        "measurements": measurements,
    }
