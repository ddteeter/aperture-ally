"""Subject vs background, on device (Apple Vision via PyObjC; macOS 14+). Spike: branch spike/subject-vision.

For each photo's overview image: Vision's foreground mask, image classification and a feature print. With the
mask: how much of the frame the subject fills and whether it touches an edge (likely cut off), background vs
subject sharpness in the same photo (relative, so far sturdier than absolute numbers: < ~0.6 the background is
clearly softer; > 1 the subject is softer than the background, i.e. focus missed or motion blur), background
busyness (edge density), and subject vs background brightness.

Measured on the spike's 20 desk photos: ~40 ms of Vision work per photo once warm; clean masks for a single
product; touching objects merge into one subject (so treat it as evidence, not truth). Elsewhere than macOS, or
without the Vision framework, this module does nothing and the rest of the pipeline is unchanged.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

log = logging.getLogger(__name__)
_lock = threading.Lock()  # Vision is thread-safe in principle; one request at a time keeps memory flat
_available: bool | None = None


def vision_available() -> bool:
    global _available
    if _available is None:
        if sys.platform != "darwin":
            _available = False
        else:
            try:
                import Quartz  # noqa: F401
                import Vision

                _available = hasattr(Vision, "VNGenerateForegroundInstanceMaskRequest")
            except Exception:
                _available = False
    return _available


# --- pure measurements (testable anywhere) --------------------------------------------------------------------
def subject_measures(gray: np.ndarray, mask: np.ndarray) -> dict[str, Any] | None:
    """Measurements from an 8-bit grayscale image and a boolean subject mask of the same size."""
    h, w = gray.shape
    m = mask.astype(bool)
    if m.sum() < max(400, 0.002 * h * w):
        return None
    k = max(3, round(min(h, w) * 0.01)) | 1  # keep away from the mask edge: the outline is itself a strong gradient
    kernel = np.ones((k, k), np.uint8)
    subj = cv2.erode(m.astype(np.uint8), kernel) > 0
    bg = cv2.erode((~m).astype(np.uint8), kernel) > 0
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    edges = cv2.Canny(gray, 60, 150) > 0
    ys, xs = np.nonzero(m)
    x0, x1, y0, y1 = xs.min() / w, (xs.max() + 1) / w, ys.min() / h, (ys.max() + 1) / h
    margin = 0.005
    out: dict[str, Any] = {
        "fraction": round(float(m.mean()), 3),
        "box": [round(x0, 3), round(y0, 3), round(x1 - x0, 3), round(y1 - y0, 3)],
        "centre": [round(float(xs.mean() / w), 3), round(float(ys.mean() / h), 3)],
        "touches_edge": [side for side, hit in (("left", x0 < margin), ("right", x1 > 1 - margin),
                                                 ("top", y0 < margin), ("bottom", y1 > 1 - margin)) if hit],
    }
    if subj.sum() >= 200 and bg.sum() >= 200:
        s_var, b_var = float(lap[subj].var()), float(lap[bg].var())
        out["background_to_subject_sharpness"] = round(b_var / s_var, 3) if s_var > 1e-6 else None
        out["background_busyness"] = round(float(edges[bg].mean()), 4)
        out["subject_mean_luminance"] = round(float(gray[subj].mean()), 1)
        out["background_mean_luminance"] = round(float(gray[bg].mean()), 1)
    return out


def featureprint_distance(a: np.ndarray | None, b: np.ndarray | None) -> float | None:
    """Euclidean distance between two Vision feature prints (~0.1 same scene; ~1 a different subject)."""
    if a is None or b is None or a.shape != b.shape:
        return None
    return round(float(np.linalg.norm(a - b)), 3)


def load_featureprint(path: str | Path | None) -> np.ndarray | None:
    if not path:
        return None
    try:
        return np.load(path)
    except Exception:
        return None


# --- Vision ------------------------------------------------------------------------------------------------------
def _pixelbuffer(pb) -> np.ndarray:
    import Quartz

    Quartz.CVPixelBufferLockBaseAddress(pb, 0)
    try:
        w, h = Quartz.CVPixelBufferGetWidth(pb), Quartz.CVPixelBufferGetHeight(pb)
        bpr = Quartz.CVPixelBufferGetBytesPerRow(pb)
        fmt = Quartz.CVPixelBufferGetPixelFormatType(pb)
        buf = Quartz.CVPixelBufferGetBaseAddress(pb).as_buffer(bpr * h)
        if fmt == Quartz.kCVPixelFormatType_OneComponent32Float:
            return np.frombuffer(buf, dtype=np.float32).reshape(h, bpr // 4)[:, :w].copy()
        if fmt == Quartz.kCVPixelFormatType_OneComponent8:
            return np.frombuffer(buf, dtype=np.uint8).reshape(h, bpr)[:, :w].astype(np.float32) / 255
        raise RuntimeError(f"unexpected mask pixel format {fmt}")
    finally:
        Quartz.CVPixelBufferUnlockBaseAddress(pb, 0)


def _featureprint_vector(obs) -> np.ndarray:
    import Vision

    # PyObjC passes computeDistance's out-pointer as an input, so the distance is computed from the raw vector.
    dt = np.float32 if obs.elementType() == Vision.VNElementTypeFloat else np.float64
    return np.frombuffer(bytes(obs.data()), dtype=dt)[: obs.elementCount()].copy()


def analyze(image_path: Path, out_dir: Path) -> dict[str, Any] | None:
    """Run Vision on `image_path` (the overview JPEG) and measure. Writes subject_mask.png and featureprint.npy
    into `out_dir`. Returns None when Vision isn't available or fails (the caller carries on without it)."""
    if not vision_available():
        return None
    import Vision
    from Foundation import NSURL

    t0 = time.perf_counter()
    try:
        with _lock:
            handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(image_path)), None)
            mask_req = Vision.VNGenerateForegroundInstanceMaskRequest.alloc().init()
            cls_req = Vision.VNClassifyImageRequest.alloc().init()
            fp_req = Vision.VNGenerateImageFeaturePrintRequest.alloc().init()
            ok, err = handler.performRequests_error_([mask_req, cls_req, fp_req], None)
            if not ok:
                log.info("Vision failed on %s: %s", image_path.name, err)
                return None
            mask = None
            res = mask_req.results() or []
            if res:
                pb, _ = res[0].generateScaledMaskForImageForInstances_fromRequestHandler_error_(
                    res[0].allInstances(), handler, None)
                if pb is not None:
                    mask = _pixelbuffer(pb) > 0.5
            labels = sorted(((str(o.identifier()), float(o.confidence())) for o in (cls_req.results() or [])),
                            key=lambda x: -x[1])
            fps = fp_req.results() or []
            fp = _featureprint_vector(fps[0]) if fps else None
    except Exception as exc:  # never let the subject step break ingest/coaching
        log.warning("subject analysis failed on %s: %s", image_path.name, exc)
        return None
    vision_ms = (time.perf_counter() - t0) * 1000

    out: dict[str, Any] = {"labels": [[n, round(c, 2)] for n, c in labels[:5] if c >= 0.1], "subject": None}
    if fp is not None:
        fp_path = out_dir / "featureprint.npy"
        np.save(fp_path, fp)
        out["featureprint_path"] = str(fp_path)
    if mask is not None:
        gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if gray is not None and gray.shape != mask.shape:
            mask = cv2.resize(mask.astype(np.uint8), (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
        if gray is not None:
            out["subject"] = subject_measures(gray, mask)
            mpath = out_dir / "subject_mask.png"
            cv2.imwrite(str(mpath), (mask.astype(np.uint8) * 255))
            out["mask_path"] = str(mpath)
    out["ms"] = {"vision": round(vision_ms, 1), "total": round((time.perf_counter() - t0) * 1000, 1)}
    return out


def prewarm() -> None:
    """Load Vision's models now (≈0.6–1.6 s cold) so the first photo of a session doesn't pay for it."""
    if not vision_available():
        return
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        img = np.full((240, 320, 3), 90, np.uint8)
        cv2.rectangle(img, (100, 70), (220, 170), (220, 220, 220), -1)
        path = Path(d) / "warm.jpg"
        cv2.imwrite(str(path), img)
        analyze(path, Path(d))
