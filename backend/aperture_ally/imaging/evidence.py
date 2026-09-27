"""Build model/UI evidence for a capture: overview, thumbnail, region crops, measurements.

Everything is orientation-normalized (EXIF transpose) before coordinates are applied, so a region
selected on the displayed overview maps to the same pixels in the full-resolution crop.
"""

from __future__ import annotations

import io
import logging
import time
from pathlib import Path
from typing import Any

import cv2
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
    img.save(tmp, "JPEG", quality=quality)
    tmp.replace(path)


def write_clip_overlay(arr: np.ndarray, size: tuple[int, int], path: Path) -> None:
    """Transparent PNG at overview size: red where the JPEG is pure white, blue where it is pure black.

    Built from full-resolution masks and area-downsampled, so even small blown specks stay visible.
    """
    small = M.subsample_nearest(arr, 3000)
    r, g, b = cv2.split(np.ascontiguousarray(small))
    hi = (cv2.max(cv2.max(r, g), b) >= M.HI).astype(np.float32)
    lo = (cv2.min(cv2.min(r, g), b) <= M.LO).astype(np.float32)
    hi = cv2.resize(hi, size, interpolation=cv2.INTER_AREA)
    lo = cv2.resize(lo, size, interpolation=cv2.INTER_AREA)
    rgba = np.zeros((size[1], size[0], 4), np.uint8)
    hi_a = np.clip(hi * 4, 0, 1)
    lo_a = np.clip(lo * 4, 0, 1)
    rgba[..., 0] = np.where(hi_a >= lo_a, 255, 40)
    rgba[..., 1] = np.where(hi_a >= lo_a, 40, 120)
    rgba[..., 2] = np.where(hi_a >= lo_a, 40, 255)
    rgba[..., 3] = (np.maximum(hi_a, lo_a) * 220).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.png")
    Image.fromarray(rgba, "RGBA").save(tmp, "PNG", optimize=False)
    tmp.replace(path)


def ensure_clip_overlay(image_path: Path, overview: dict[str, Any], out: Path) -> Path:
    if not out.exists():
        img, _ = load_oriented_srgb(image_path)
        write_clip_overlay(np.asarray(img), (overview["width"], overview["height"]), out)
    return out


def build_evidence(
    image_path: Path,
    out_dir: Path,
    regions: list[Region],
    *,
    overview_long_edge: int = 1600,
    crop_max_edge: int = 1024,
    max_crops: int = 3,
) -> dict[str, Any]:
    t: dict[str, float] = {}
    clock = time.perf_counter
    t0 = clock()
    img, color_info = load_oriented_srgb(image_path)
    W, H = img.size
    arr = np.asarray(img)
    t["decode_orient_color_ms"] = (clock() - t0) * 1000

    t0 = clock()
    scale = min(1.0, overview_long_edge / max(W, H))
    # INTER_AREA is the appropriate (and multi-threaded) filter for large downscales.
    overview = (Image.fromarray(cv2.resize(arr, (round(W * scale), round(H * scale)), interpolation=cv2.INTER_AREA))
                if scale < 1 else img)
    _save_jpeg(overview, out_dir / "overview.jpg")
    thumb = overview.copy()
    thumb.thumbnail((360, 360), Image.Resampling.LANCZOS)
    _save_jpeg(thumb, out_dir / "thumb.jpg", quality=80)
    t["overview_thumb_ms"] = (clock() - t0) * 1000
    t0 = clock()

    crops: list[dict[str, Any]] = []
    selected = [r.clamp() for r in regions][:max_crops]
    auto = False
    if not selected:
        x, y, w, h = M.auto_detail_region(arr)
        selected = [Region(id="auto1", label="auto: highest local detail (not user-selected)", x=x, y=y, w=w, h=h)]
        auto = True
    t["auto_region_ms"] = (clock() - t0) * 1000
    t0 = clock()

    region_metrics: dict[str, Any] = {}
    for r in selected:
        x0, y0 = int(r.x * W), int(r.y * H)
        x1, y1 = max(x0 + 1, int((r.x + r.w) * W)), max(y0 + 1, int((r.y + r.h) * H))
        sub = arr[y0:y1, x0:x1]
        cscale = min(1.0, crop_max_edge / max(sub.shape[1], sub.shape[0]))
        crop = Image.fromarray(sub if cscale == 1 else cv2.resize(
            sub, (round(sub.shape[1] * cscale), round(sub.shape[0] * cscale)), interpolation=cv2.INTER_AREA))
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
            **M.tonal_stats(sub),  # includes the region's own histogram (the UI reads regions first)
            **M.sharpness(sub),  # at native resolution
        }

    t["crops_and_region_stats_ms"] = (clock() - t0) * 1000
    t0 = clock()
    global_stats = {**M.tonal_stats(M.subsample_nearest(arr)), **M.sharpness(np.asarray(overview))}
    t["global_stats_ms"] = (clock() - t0) * 1000
    measurements = {
        "image": {"width": W, "height": H, **color_info},
        "global": global_stats,
        "regions": region_metrics,
        "notes": {"global_sharpness_scale": "measured on overview", "region_sharpness_scale": "native pixels"},
        "caveats": M.CAVEATS,
    }
    return {
        "width": W,
        "height": H,
        "overview": {"path": str(out_dir / "overview.jpg"), "width": overview.width, "height": overview.height},
        "thumb": str(out_dir / "thumb.jpg"),
        "clip_overlay": str(out_dir / "clip_overlay.png"),  # generated on first request (off the latency path)
        "crops": crops,
        "measurements": measurements,
        "timings": {k: round(v, 2) for k, v in t.items()},
        "source_bytes": image_path.stat().st_size,
    }
