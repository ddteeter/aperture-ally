"""Framing similarity between two captures: "is this the same composition?"

Works on the overview JPEGs, with two complementary measures; the higher one wins:

* **Layout** (whole-scene structure): a 128 px edge map (gradient magnitude, normalized), so a brighter
  or darker retake of the same scene still matches. Carries product shots, where outlines dominate.
* **Texture** (fine structure in place): a 512 px high-pass image with local contrast normalized away,
  so moving or reshaping the light (a glare hotspot that moved, a gradient across the frame) cancels
  out and only the weave/mesh pattern and where it sits in the frame remain. Carries fabric close-ups,
  which have almost no large-scale layout. A zoom changes the pattern's scale and a different fabric
  has a different pattern, so both score near zero.

Fabric close-ups also fool the layout map: at 128 px a weave aliases into a pattern that looks the
same after a zoom. Each frame therefore tests its own layout map against a x1.3 zoom of itself; when
the map cannot tell the difference (``_LAYOUT_SELF_MATCH``), the frame is texture-dominated and only
the texture measure is used for it.

For each measure translation is estimated with phase correlation, the maps are compared
(zero-normalized cross-correlation) where they overlap after that shift, and the result is scaled by
the overlap fraction. Same framing scores near 1; a small nudge stays high; a zoom, a tight crop, a
reframe or another subject drops well below ``COMPARABLE``.

This is a heuristic for "is a side-by-side fair?", not a composition judgement.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

# Scores at/above this mean the two frames show the same composition closely enough that region
# measurements and a before/after view are fair. Calibrated in tests/test_framing.py.
COMPARABLE = 0.65

WIDTH = 128  # layout map width
TEX_WIDTH = 512  # texture map width
_MAX_ASPECT_LOG_DIFF = 0.08  # ~8% aspect-ratio difference: different crop/orientation
_MIN_TEXTURE = 0.08  # RMS high-pass (sqrt-tone units) below this: no texture to match (flat/blank frame)
_MIN_PEAK = 0.15  # phase-correlation peak below this: no reliable shift (unrelated or periodic content)
_SELF_ZOOM = 1.3
_LAYOUT_SELF_MATCH = 0.5  # layout map vs its own x1.3 zoom at/above this: layout blind to zoom (texture frame)

_lock = threading.Lock()


@dataclass(frozen=True)
class Signature:
    layout: np.ndarray
    texture: np.ndarray
    texture_energy: float
    layout_reliable: bool  # False for texture-dominated frames (see module docstring)


@dataclass(frozen=True)
class Match:
    score: float
    basis: str  # "layout" | "texture" | "none"


_sig_cache: OrderedDict[tuple[str, int], Signature] = OrderedDict()
_score_cache: OrderedDict[tuple, Match] = OrderedDict()
_SIG_MAX, _SCORE_MAX = 256, 8192  # ~200 KB per signature


def _layout(gray: np.ndarray) -> np.ndarray:
    h, w = gray.shape
    small = cv2.resize(gray, (WIDTH, max(8, round(WIDTH * h / w))), interpolation=cv2.INTER_AREA).astype(np.float32)
    small = np.sqrt(small + 1.0)  # log-ish tone curve: a darker exposure keeps its edge structure
    gx = cv2.Sobel(small, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(small, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.GaussianBlur(cv2.magnitude(gx, gy), (0, 0), 1.2)
    return (mag - mag.mean()) / (mag.std() + 1e-6)


def _texture(gray: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = gray.shape
    th = max(16, round(TEX_WIDTH * h / w))
    small = cv2.resize(gray, (TEX_WIDTH, th), interpolation=cv2.INTER_AREA).astype(np.float32)
    small = np.sqrt(small + 1.0)
    hp = small - cv2.GaussianBlur(small, (0, 0), 3)
    sq = cv2.pyrDown(hp * hp)  # local energy at half resolution: same result, a third of the cost
    local = cv2.resize(cv2.GaussianBlur(sq, (0, 0), 4), (TEX_WIDTH, th), interpolation=cv2.INTER_LINEAR)
    energy = float(np.sqrt(local.mean()))
    # Divide out local contrast (with a floor so flat or clipped areas stay ~0 instead of amplified noise).
    norm = hp / np.sqrt(local + (0.25 * energy) ** 2 + 1e-4)
    fh = max(16, th - th % 64) if th > 64 else th  # DFT-friendly height keeps phase correlation fast
    y0 = (th - fh) // 2
    # int8 keeps a cached map at ~160 KB; +-4 (x31) covers the normalized range.
    q = np.clip(np.rint(norm[y0:y0 + fh] * 31.0), -127, 127).astype(np.int8)
    return np.ascontiguousarray(q), energy


def signature_file(overview: Path) -> Path:
    return overview.with_name(overview.stem + ".framing.npz")


def compute_signature(path: Path) -> Signature:
    gray = cv2.imread(str(path), cv2.IMREAD_REDUCED_GRAYSCALE_2)  # one decode feeds both maps
    if gray is None:
        raise ValueError(f"cannot read {path}")
    tex, energy = _texture(gray)
    layout = _layout(gray)
    h, w = gray.shape
    cw, ch = int(w / _SELF_ZOOM), int(h / _SELF_ZOOM)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    zoomed = _layout(cv2.resize(gray[y0:y0 + ch, x0:x0 + cw], (w // 4, h // 4), interpolation=cv2.INTER_AREA))
    return Signature(layout, tex, energy, _aligned_zncc(layout, zoomed) < _LAYOUT_SELF_MATCH)


def write_signature(overview: Path) -> Signature:
    """Compute and store the signature beside the overview (done when evidence is built)."""
    sig = compute_signature(overview)
    out = signature_file(overview)
    tmp = out.with_name(out.name + ".tmp.npz")
    np.savez(tmp, layout=sig.layout.astype(np.float16), texture=sig.texture,
             meta=np.array([sig.texture_energy, float(sig.layout_reliable)], np.float32))
    tmp.replace(out)
    return sig


def _load_signature(overview: Path) -> Signature | None:
    f = signature_file(overview)
    try:
        if f.stat().st_mtime_ns < overview.stat().st_mtime_ns:
            return None
        with np.load(f) as z:
            meta = z["meta"]
            return Signature(z["layout"].astype(np.float32), z["texture"], float(meta[0]), bool(meta[1]))
    except (OSError, KeyError, ValueError):
        return None


def _signature(path: Path) -> Signature:
    key = (str(path), path.stat().st_mtime_ns)
    with _lock:
        hit = _sig_cache.get(key)
        if hit is not None:
            _sig_cache.move_to_end(key)
            return hit
    sig = _load_signature(path)
    if sig is None:
        try:
            sig = write_signature(path)  # older evidence: compute once, keep on disk
        except OSError:
            sig = compute_signature(path)
    with _lock:
        _sig_cache[key] = sig
        if len(_sig_cache) > _SIG_MAX:
            _sig_cache.popitem(last=False)
    return sig


def _zncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    den = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return float((a * b).sum()) / den if den > 1e-9 else 0.0


def _shifted_overlap(a: np.ndarray, b: np.ndarray, dx: int, dy: int) -> tuple[np.ndarray, np.ndarray]:
    """Overlapping windows of ``a`` and ``b`` where b(x, y) ≈ a(x - dx, y - dy)."""
    h, w = a.shape
    ax0, ax1 = max(0, -dx), min(w, w - dx)
    ay0, ay1 = max(0, -dy), min(h, h - dy)
    return a[ay0:ay1, ax0:ax1], b[ay0 + dy:ay1 + dy, ax0 + dx:ax1 + dx]


_windows: dict[tuple[int, int], np.ndarray] = {}


def _window(w: int, h: int) -> np.ndarray:
    win = _windows.get((w, h))
    if win is None:
        win = _windows[(w, h)] = cv2.createHanningWindow((w, h), cv2.CV_32F)
    return win


_SHIFT_WINDOW = 256  # shift is estimated on a centred crop this wide (covers shifts up to ~25% of the frame)


def _aligned_zncc(a: np.ndarray, b: np.ndarray) -> float:
    """Best overlap-weighted ZNCC of two same-aspect maps after phase-correlation alignment (0..1)."""
    a, b = a.astype(np.float32), b.astype(np.float32)  # always fresh copies: see phaseCorrelate below
    ha, wa = a.shape
    if b.shape != a.shape:
        b = cv2.resize(b, (wa, ha), interpolation=cv2.INTER_AREA)
    cw, ch = min(wa, _SHIFT_WINDOW), min(ha, _SHIFT_WINDOW)
    x0, y0 = (wa - cw) // 2, (ha - ch) // 2
    ca, cb = a[y0:y0 + ch, x0:x0 + cw].copy(), b[y0:y0 + ch, x0:x0 + cw].copy()
    # OpenCV's phaseCorrelate applies the window to its first input in place, hence the copies.
    (sx, sy), peak = cv2.phaseCorrelate(ca, cb, _window(cw, ch))
    # Phase correlation's sign/rounding is checked both ways; zero shift covers a failed estimate. A weak
    # peak means the "shift" is noise, and on periodic texture a noise shift can still line up by chance.
    shifts = {(round(sx), round(sy)), (-round(sx), -round(sy)), (0, 0)} if peak >= _MIN_PEAK else {(0, 0)}
    best = 0.0
    for dx, dy in sorted(shifts):
        if abs(dx) >= wa // 2 or abs(dy) >= ha // 2:
            continue
        wa_, wb_ = _shifted_overlap(a, b, dx, dy)
        if wa_.size < 64:
            continue
        best = max(best, _zncc(wa_, wb_) * wa_.size / a.size)
    return min(1.0, max(0.0, best))


def match_signatures(a: Signature, b: Signature) -> Match:
    (ha, wa), (hb, wb) = a.layout.shape, b.layout.shape
    if abs(math.log((wa / ha) / (wb / hb))) > _MAX_ASPECT_LOG_DIFF:
        return Match(0.0, "none")
    has_texture = min(a.texture_energy, b.texture_energy) >= _MIN_TEXTURE
    if not (a.layout_reliable and b.layout_reliable):
        # Texture-dominated: the layout map would call a zoomed-in weave "the same framing".
        if not has_texture:
            return Match(0.0, "none")
        return Match(round(_aligned_zncc(a.texture, b.texture), 3), "texture")
    layout = _aligned_zncc(a.layout, b.layout)
    if layout >= COMPARABLE or not has_texture:
        return Match(round(layout, 3), "layout")  # already comparable; the texture term could only raise it
    texture = _aligned_zncc(a.texture, b.texture)
    if texture > layout:
        return Match(round(texture, 3), "texture")
    return Match(round(layout, 3), "layout")


def score_signatures(a: Signature, b: Signature) -> float:
    return match_signatures(a, b).score


def framing_match(path_a: Path | str, path_b: Path | str) -> Match:
    """Similarity of composition (score 0..1, 1 = same framing) and which measure decided it. Cached per pair."""
    pa, pb = sorted([Path(path_a), Path(path_b)], key=str)  # same pair, same order: deterministic and cacheable
    key = ((str(pa), pa.stat().st_mtime_ns), (str(pb), pb.stat().st_mtime_ns))
    with _lock:
        hit = _score_cache.get(key)
        if hit is not None:
            return hit
    m = match_signatures(_signature(pa), _signature(pb))
    with _lock:
        _score_cache[key] = m
        if len(_score_cache) > _SCORE_MAX:
            _score_cache.popitem(last=False)
    return m


def framing_score(path_a: Path | str, path_b: Path | str) -> float:
    return framing_match(path_a, path_b).score


def overview_path(evidence: dict) -> Path | None:
    p = (evidence or {}).get("overview", {}).get("path")
    return Path(p) if p and Path(p).exists() else None


def framing_detail(ev_a: dict, ev_b: dict) -> Match | None:
    a, b = overview_path(ev_a), overview_path(ev_b)
    if a is None or b is None:
        return None
    try:
        return framing_match(a, b)
    except Exception:
        return None


def framing_between(ev_a: dict, ev_b: dict) -> dict | None:
    """{score, comparable} for two captures' evidence, or None when either overview is missing."""
    m = framing_detail(ev_a, ev_b)
    return None if m is None else {"score": m.score, "comparable": m.score >= COMPARABLE}
