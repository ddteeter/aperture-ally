"""Inexpensive local measurements.

* Clipping is measured on the *rendered* 8-bit image (JPEG or developed preview). It is not evidence
  that RAW data is unrecoverably clipped.
* Sharpness indicators (variance of Laplacian, mean Tenengrad) are *relative* evidence for comparing
  the same region across comparable frames. They depend on texture, noise, in-camera sharpening,
  magnification and light, so there is no universal pass threshold and no blur-cause diagnosis.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

CAVEATS = [
    "Clipping fractions are measured on the rendered 8-bit JPEG/preview, not the RAW sensor data.",
    "Sharpness indicators are relative: compare the same region between comparable frames only; "
    "texture, noise, sharpening, magnification and lighting all change them.",
    "No absolute quality score is computed.",
]

HI = 254
LO = 1


_LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def luminance(rgb: np.ndarray) -> np.ndarray:
    """Rec.709 luma on sRGB-encoded values (a display-referred approximation)."""
    return rgb.reshape(-1, 3).astype(np.float32) @ _LUMA


def _hist_percentile(hist256: np.ndarray, p: float) -> float:
    cdf = np.cumsum(hist256)
    return float(np.searchsorted(cdf, p * cdf[-1]))


def tonal_stats(rgb: np.ndarray, bins: int = 64) -> dict[str, Any]:
    lum = luminance(rgb)
    h256 = np.bincount(np.clip(lum, 0, 255).astype(np.uint8), minlength=256)
    total = float(lum.size)
    hist = h256.reshape(bins, 256 // bins).sum(axis=1)
    r, g, b = cv2.split(np.ascontiguousarray(rgb))
    chmax = cv2.max(cv2.max(r, g), b)
    chmin = cv2.min(cv2.min(r, g), b)
    return {
        "histogram": (hist / total).round(5).tolist(),
        "mean_luminance": round(float(lum.mean()), 2),
        "p01_luminance": _hist_percentile(h256, 0.01),
        "p99_luminance": _hist_percentile(h256, 0.99),
        "highlight_clip_fraction": round(float((chmax >= HI).mean()), 5),
        "shadow_clip_fraction": round(float((chmin <= LO).mean()), 5),
        "channel_highlight_clip": {c: round(float((ch >= HI).mean()), 5) for c, ch in zip("RGB", (r, g, b), strict=True)},
        "channel_shadow_clip": {c: round(float((ch <= LO).mean()), 5) for c, ch in zip("RGB", (r, g, b), strict=True)},
    }


def sharpness(rgb: np.ndarray) -> dict[str, float]:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return {
        "laplacian_var": round(float(lap.var()), 2),
        "tenengrad_mean": round(float((gx * gx + gy * gy).mean()), 2),
        "gradient_p90": round(float(np.percentile(np.sqrt(gx * gx + gy * gy), 90)), 2),
    }


def subsample_nearest(rgb: np.ndarray, max_edge: int = 2000) -> np.ndarray:
    """Nearest-neighbour subsample keeps real pixel values (no averaging that hides clipping)."""
    h, w = rgb.shape[:2]
    step = max(1, int(np.ceil(max(h, w) / max_edge)))
    return rgb[::step, ::step]


def auto_detail_region(rgb: np.ndarray, cols: int = 6, rows: int = 4) -> tuple[float, float, float, float]:
    """Normalized (x, y, w, h) of the grid tile with the most local detail (Laplacian variance)."""
    small = subsample_nearest(rgb, 1200)
    gray = cv2.cvtColor(np.ascontiguousarray(small), cv2.COLOR_RGB2GRAY).astype(np.float32)
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    h, w = gray.shape
    best, best_rc = -1.0, (0, 0)
    for r in range(rows):
        for c in range(cols):
            tile = lap[r * h // rows:(r + 1) * h // rows, c * w // cols:(c + 1) * w // cols]
            v = float(tile.var())
            if v > best:
                best, best_rc = v, (r, c)
    r, c = best_rc
    return c / cols, r / rows, 1 / cols, 1 / rows


def region_comparable(a: dict[str, Any], b: dict[str, Any], exif_a: dict, exif_b: dict) -> tuple[bool, list[str]]:
    """Whether two regional measurements may be compared numerically."""
    reasons = []
    if a.get("rect") != b.get("rect"):
        reasons.append("region rectangles differ")
    if a.get("px_size") and b.get("px_size"):
        (wa, ha), (wb, hb) = a["px_size"], b["px_size"]
        if abs(wa - wb) / max(wa, wb) > 0.05 or abs(ha - hb) / max(ha, hb) > 0.05:
            reasons.append("region pixel sizes differ >5%")
    fa, fb = exif_a.get("focal_length_mm"), exif_b.get("focal_length_mm")
    if fa and fb and abs(fa - fb) / max(fa, fb) > 0.03:
        reasons.append("focal length changed (magnification differs)")
    comparable = not reasons
    if comparable:
        reasons.append("framing/content similarity is not verified automatically; treat as indicative only")
    return comparable, reasons
