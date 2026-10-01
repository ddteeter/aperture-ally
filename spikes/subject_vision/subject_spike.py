"""Spike: on-device subject vs background with Apple Vision, and what it lets us measure.

For each photo: Vision's foreground instance mask (macOS 14+), saliency, image classification and a feature print;
then subject / background sharpness (Laplacian variance, Tenengrad), background busyness (edge density), subject
fill / position / edge contact, subject vs background brightness. Writes overlays + a JSON report to OUT (local
scratch only; the photos are the owner's and never leave this Mac).

uv run --no-project --python 3.12 --with pyobjc-framework-Vision --with pyobjc-framework-Quartz \
    --with opencv-python-headless --with numpy python subject_spike.py OUT PHOTO...
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import Foundation
import Quartz
import Vision
from Foundation import NSURL

MAX_SIDE = 2048  # analyse at this size (the coach's crops are native; this is about whole-frame structure)


def load(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    s = MAX_SIDE / max(h, w)
    return cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img


def pixelbuffer_to_array(pb) -> np.ndarray:
    Quartz.CVPixelBufferLockBaseAddress(pb, 0)
    try:
        w, h = Quartz.CVPixelBufferGetWidth(pb), Quartz.CVPixelBufferGetHeight(pb)
        bpr = Quartz.CVPixelBufferGetBytesPerRow(pb)
        fmt = Quartz.CVPixelBufferGetPixelFormatType(pb)
        base = Quartz.CVPixelBufferGetBaseAddress(pb)
        buf = base.as_buffer(bpr * h)
        if fmt == Quartz.kCVPixelFormatType_OneComponent32Float:
            a = np.frombuffer(buf, dtype=np.float32).reshape(h, bpr // 4)[:, :w]
        elif fmt == Quartz.kCVPixelFormatType_OneComponent8:
            a = np.frombuffer(buf, dtype=np.uint8).reshape(h, bpr)[:, :w].astype(np.float32) / 255
        else:
            raise RuntimeError(f"pixel format {fmt}")
        return a.copy()
    finally:
        Quartz.CVPixelBufferUnlockBaseAddress(pb, 0)


def vision(path: Path) -> dict:
    url = NSURL.fileURLWithPath_(str(path))
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
    mask_req = Vision.VNGenerateForegroundInstanceMaskRequest.alloc().init()
    sal_req = Vision.VNGenerateObjectnessBasedSaliencyImageRequest.alloc().init()
    cls_req = Vision.VNClassifyImageRequest.alloc().init()
    fp_req = Vision.VNGenerateImageFeaturePrintRequest.alloc().init()
    out: dict = {"ms": {}}
    for name, req in (("mask", mask_req), ("saliency", sal_req), ("classify", cls_req), ("featureprint", fp_req)):
        t = time.monotonic()
        ok, err = handler.performRequests_error_([req], None)
        out["ms"][name] = round((time.monotonic() - t) * 1000, 1)
        if not ok:
            out[f"{name}_error"] = str(err)
    res = mask_req.results() or []
    out["per_instance"] = []
    if res:
        obs = res[0]
        # Each object on its own: its share of the frame, centre, and what the classifier says about its box.
        idxset, ids = obs.allInstances(), []
        i = idxset.firstIndex()
        while i != Foundation.NSNotFound and len(ids) < 10:
            ids.append(i)
            i = idxset.indexGreaterThanIndex_(i)
        for idx in ids:
            pbi, _ = obs.generateScaledMaskForImageForInstances_fromRequestHandler_error_(
                Foundation.NSIndexSet.indexSetWithIndex_(idx), handler, None)
            if pbi is None:
                continue
            mi = pixelbuffer_to_array(pbi) > 0.5
            ys, xs = np.nonzero(mi)
            if not len(xs):
                continue
            h, w = mi.shape
            x0, x1, y0, y1 = xs.min() / w, xs.max() / w, ys.min() / h, ys.max() / h
            creq = Vision.VNClassifyImageRequest.alloc().init()
            creq.setRegionOfInterest_(Quartz.CGRectMake(x0, 1 - y1, x1 - x0, y1 - y0))  # Vision: origin bottom-left
            handler.performRequests_error_([creq], None)
            labs = sorted(((o.identifier(), float(o.confidence())) for o in (creq.results() or [])), key=lambda x: -x[1])
            out["per_instance"].append({"index": int(idx), "fraction": round(float(mi.mean()), 3),
                                        "centre": [round(float(xs.mean() / w), 3), round(float(ys.mean() / h), 3)],
                                        "labels": [(n, round(c, 2)) for n, c in labs[:4] if c > 0.1]})
        t = time.monotonic()
        pb, err = obs.generateScaledMaskForImageForInstances_fromRequestHandler_error_(obs.allInstances(), handler, None)
        out["ms"]["mask_scale"] = round((time.monotonic() - t) * 1000, 1)
        out["mask"] = pixelbuffer_to_array(pb) if pb is not None else None
        out["instances"] = len(obs.allInstances())
    else:
        out["mask"], out["instances"] = None, 0
    sal = sal_req.results() or []
    out["salient_boxes"] = []
    if sal:
        for o in sal[0].salientObjects() or []:
            b = o.boundingBox()
            out["salient_boxes"].append([round(b.origin.x, 3), round(1 - b.origin.y - b.size.height, 3),
                                         round(b.size.width, 3), round(b.size.height, 3), round(o.confidence(), 2)])
    labels = sorted(((o.identifier(), float(o.confidence())) for o in (cls_req.results() or [])), key=lambda x: -x[1])
    out["labels"] = [(n, round(c, 2)) for n, c in labels[:6] if c > 0.05]
    fp = fp_req.results() or []
    out["featureprint"] = fp[0] if fp else None
    return out


def lap_var(gray: np.ndarray, m: np.ndarray) -> float | None:
    if m.sum() < 500:
        return None
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap[m].var())


def tenengrad(gray: np.ndarray, m: np.ndarray) -> float | None:
    if m.sum() < 500:
        return None
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    return float(np.mean((gx * gx + gy * gy)[m]))


def measures(img: np.ndarray, mask: np.ndarray) -> dict:
    h, w = img.shape[:2]
    m = cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR) > 0.5
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    k = max(3, round(min(h, w) * 0.01)) | 1
    kernel = np.ones((k, k), np.uint8)
    subj = cv2.erode(m.astype(np.uint8), kernel) > 0  # keep away from the mask edge (the edge itself is a strong gradient)
    bg = cv2.erode((~m).astype(np.uint8), kernel) > 0
    edges = cv2.Canny(gray, 60, 150) > 0
    ys, xs = np.nonzero(m)
    out: dict = {"subject_fraction": round(float(m.mean()), 3)}
    if len(xs):
        x0, x1, y0, y1 = xs.min() / w, xs.max() / w, ys.min() / h, ys.max() / h
        out["subject_box"] = [round(x0, 3), round(y0, 3), round(x1 - x0, 3), round(y1 - y0, 3)]
        out["subject_centre"] = [round(float(xs.mean() / w), 3), round(float(ys.mean() / h), 3)]
        edge = 0.005
        out["touches_edge"] = [s for s, hit in (("left", x0 < edge), ("right", x1 > 1 - edge), ("top", y0 < edge),
                                                ("bottom", y1 > 1 - edge)) if hit]
    s_lv, b_lv = lap_var(gray, subj), lap_var(gray, bg)
    s_tg, b_tg = tenengrad(gray, subj), tenengrad(gray, bg)
    out.update({
        "subject_laplacian_var": round(s_lv, 1) if s_lv else None,
        "background_laplacian_var": round(b_lv, 1) if b_lv else None,
        "background_to_subject_sharpness": round(b_lv / s_lv, 3) if s_lv and b_lv else None,
        "background_to_subject_tenengrad": round(b_tg / s_tg, 3) if s_tg and b_tg else None,
        "background_edge_density": round(float(edges[bg].mean()), 4) if bg.any() else None,
        "subject_edge_density": round(float(edges[subj].mean()), 4) if subj.any() else None,
        "subject_mean_luminance": round(float(gray[subj].mean()), 1) if subj.any() else None,
        "background_mean_luminance": round(float(gray[bg].mean()), 1) if bg.any() else None,
    })
    return out


def overlay(img: np.ndarray, mask: np.ndarray, info: dict, out: Path) -> None:
    h, w = img.shape[:2]
    m = cv2.resize(mask, (w, h)) > 0.5
    vis = img.copy()
    vis[~m] = (vis[~m] * 0.35).astype(np.uint8)  # dim the background
    cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, cnts, -1, (232, 192, 121), max(2, w // 600))
    lines = [f"subject {info.get('subject_fraction')} of frame  edge: {','.join(info.get('touches_edge', [])) or '-'}",
             f"bg/subject sharpness {info.get('background_to_subject_sharpness')}  bg edges {info.get('background_edge_density')}",
             f"labels {', '.join(n for n, _ in info.get('labels', [])[:3])}"]
    for i, t in enumerate(lines):
        y = 40 + i * 38
        cv2.putText(vis, t, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(vis, t, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(out), vis, [cv2.IMWRITE_JPEG_QUALITY, 80])


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [Path(p) for p in sys.argv[2:]]
    report, prints = [], []
    for p in paths:
        t0 = time.monotonic()
        img = load(p)
        small = out_dir / f"_in_{p.stem}.jpg"
        cv2.imwrite(str(small), img, [cv2.IMWRITE_JPEG_QUALITY, 92])  # Vision on the same pixels we measure
        v = vision(small)
        row = {"photo": p.name, "vision_ms": v["ms"], "instances": v["instances"], "labels": v["labels"],
               "salient_boxes": v["salient_boxes"]}
        if v["mask"] is not None:
            row.update(measures(img, v["mask"]))
            overlay(img, v["mask"], row, out_dir / f"{p.stem}_subject.jpg")
        else:
            row["note"] = "no foreground found"
        row["total_ms"] = round((time.monotonic() - t0) * 1000, 1)
        small.unlink()
        prints.append(v["featureprint"])
        report.append(row)
        print(json.dumps(row), flush=True)
    # feature-print distance to the first photo (the shoe) and to the previous photo
    def vec(o):
        # PyObjC passes computeDistance's out-pointer as input (always None), so compute it: Euclidean distance.
        dt = np.float32 if o.elementType() == Vision.VNElementTypeFloat else np.float64
        return np.frombuffer(bytes(o.data()), dtype=dt)[: o.elementCount()]

    def dist(a, b):
        if a is None or b is None:
            return None
        return round(float(np.linalg.norm(vec(a) - vec(b))), 3)

    for i, row in enumerate(report):
        row["fp_to_first"] = dist(prints[0], prints[i])
        row["fp_to_prev"] = dist(prints[i - 1], prints[i]) if i else None
    (out_dir / "report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
