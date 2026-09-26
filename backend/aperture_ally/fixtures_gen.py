"""Generate small, redistributable SYNTHETIC fixtures for replay and tests.

These are procedural drawings (shoe-like shapes, mesh and tread textures) with controlled defects:
highlight clipping ("glare"), regional blur ("missed focus"), underexposure, missing EXIF, EXIF
orientation, a RAW+JPEG pair (the RAW is a *fake* placeholder that LibRaw cannot decode), and a
duplicate. They exercise software paths only. They are NOT photographic validation data; the mock
provider's thresholds are tuned to them. Real evaluation uses owner-supplied photos (evals/README.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, TiffImagePlugin

W, H = 2400, 1600
RNG_SEED = 7


def _bg() -> np.ndarray:
    g = np.linspace(190, 120, H, dtype=np.float32)[:, None, None]
    return np.repeat(np.repeat(g, W, axis=1), 3, axis=2).copy()


def _mesh(img: np.ndarray, x0: int, y0: int, x1: int, y1: int, color=(40, 80, 150)) -> None:
    rng = np.random.default_rng(RNG_SEED)
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    weave = (np.sin(xx / 3.1) * np.sin(yy / 3.1)) * 30 + rng.normal(0, 5, xx.shape)
    holes = ((xx.astype(int) // 14 + yy.astype(int) // 14) % 2) * 15
    for c in range(3):
        img[y0:y1, x0:x1, c] = np.clip(color[c] + weave + holes, 0, 255)


def _tread(img: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> None:
    img[y0:y1, x0:x1] = (225, 225, 220)
    rng = np.random.default_rng(RNG_SEED + 1)
    step = 46
    for yy in range(y0 + 10, y1 - 30, step):
        for xx in range(x0 + 10 + (yy // step % 2) * 20, x1 - 30, step):
            cv2.rectangle(img, (xx, yy), (xx + 26, yy + 18), (35, 35, 38), -1)
    img[y0:y1, x0:x1] += rng.normal(0, 7, (y1 - y0, x1 - x0, 3))


def _shoe(img: np.ndarray) -> None:
    pts = np.array([[420, 1080], [560, 640], [980, 520], [1500, 560], [1880, 760], [2010, 1000], [1980, 1130],
                    [440, 1140]], np.int32)
    mask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mask, [pts], 255)
    tex = img.copy()
    _mesh(tex, 400, 500, 2020, 1150)
    img[mask > 0] = tex[mask > 0]
    cv2.rectangle(img, (430, 1100), (2000, 1190), (235, 235, 230), -1)  # midsole
    cv2.ellipse(img, (1200, 860), (300, 90), -12, 200, 340, (232, 232, 232), 26)  # logo stroke


def _glare(img: np.ndarray, cx: int, cy: int, radius: int, peak: float) -> None:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    blob = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * radius ** 2)))
    img += blob[..., None] * peak


def _blur_region(img: np.ndarray, x0: int, y0: int, x1: int, y1: int, sigma: float) -> None:
    img[y0:y1, x0:x1] = cv2.GaussianBlur(img[y0:y1, x0:x1], (0, 0), sigma)


def _exif(dt: str, *, f: float = 5.6, shutter: float = 1 / 60, iso: int = 200, focal: float = 25.0,
          orientation: int = 1, flash: int = 16, program: int = 1) -> Image.Exif:
    exif = Image.Exif()
    exif[271] = "OLYMPUS CORPORATION"
    exif[272] = "E-M1MarkII"
    exif[274] = orientation
    ifd = exif.get_ifd(0x8769)
    ifd[33434] = TiffImagePlugin.IFDRational(1, round(1 / shutter)) if shutter < 1 else TiffImagePlugin.IFDRational(shutter)
    ifd[33437] = TiffImagePlugin.IFDRational(int(f * 10), 10)
    ifd[34855] = iso
    ifd[34850] = program
    ifd[37385] = flash
    ifd[37386] = TiffImagePlugin.IFDRational(int(focal * 10), 10)
    ifd[36867] = dt
    ifd[37521] = "00"
    ifd[42036] = "OLYMPUS M.12-40mm F2.8 (synthetic fixture)"
    return exif


def _save(img: np.ndarray, path: Path, exif: Image.Exif | None, rotate_for_orientation6: bool = False) -> None:
    arr = np.clip(img, 0, 255).astype(np.uint8)
    im = Image.fromarray(arr)
    if rotate_for_orientation6:
        im = im.transpose(Image.Transpose.ROTATE_90)  # stored rotated; EXIF 6 says rotate 90 CW to display
    kwargs = {"quality": 92}
    if exif is not None:
        kwargs["exif"] = exif.tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "JPEG", **kwargs)


# Region presets in normalized coords (for shot sharp-region selection in scenarios/tests).
REGIONS = {
    "mesh": {"id": "r1", "label": "forefoot mesh", "x": 0.30, "y": 0.35, "w": 0.25, "h": 0.25},
    "tread": {"id": "r1", "label": "forefoot tread", "x": 0.20, "y": 0.25, "w": 0.30, "h": 0.40},
    "heel": {"id": "r1", "label": "heel counter", "x": 0.60, "y": 0.35, "w": 0.25, "h": 0.30},
}


def generate(out: Path) -> dict[str, str]:
    """Write all fixture files into ``out``; returns name → description."""
    out.mkdir(parents=True, exist_ok=True)
    made: dict[str, str] = {}

    def hero(glare_peak=0.0):
        img = _bg()
        _shoe(img)
        if glare_peak:
            _glare(img, 1000, 760, 170, glare_peak)
        return img

    _save(hero(), out / "P9260001.JPG", _exif("2026:09:26 10:00:01", f=8))
    made["P9260001.JPG"] = "hero: whole shoe, no measurement flags"

    def upper(glare_peak: float, cx=1150, cy=760):
        img = _bg()
        _mesh(img, 0, 0, W, H)
        if glare_peak:
            _glare(img, cx, cy, 190, glare_peak)
        return img

    _save(upper(260), out / "P9260002.JPG", _exif("2026:09:26 10:02:00", f=5.6))
    made["P9260002.JPG"] = "upper mesh with large clipped hotspot over the selected region (glare)"
    _save(upper(40, cx=1950, cy=300), out / "P9260003.JPG", _exif("2026:09:26 10:02:40", f=5.6))
    made["P9260003.JPG"] = "upper mesh retake: hotspot moved off the region and not clipped (glare fixed)"

    def outsole(soft: bool):
        img = _bg()
        _tread(img, 250, 200, 2150, 1400)
        if soft:
            _blur_region(img, 250, 200, 1300, 1400, 7.0)
        return img

    _save(outsole(True), out / "P9260004.JPG", _exif("2026:09:26 10:05:00", f=2.8, shutter=1 / 125))
    made["P9260004.JPG"] = "outsole with forefoot tread region blurred (missed focus / shallow DoF)"
    _save(outsole(False), out / "P9260005.JPG", _exif("2026:09:26 10:05:40", f=8, shutter=1 / 15))
    made["P9260005.JPG"] = "outsole retake: tread sharp throughout"

    def heel(gain: float):
        img = _bg()
        _shoe(img)
        return img * gain

    _save(heel(0.28), out / "P9260006.JPG", _exif("2026:09:26 10:08:00"))
    made["P9260006.JPG"] = "heel: underexposed (dark)"
    _save(heel(1.0), out / "P9260007.JPG", _exif("2026:09:26 10:08:30"))
    made["P9260007.JPG"] = "heel retake: normal exposure"

    _save(hero(), out / "NOEXIF01.JPG", None)
    made["NOEXIF01.JPG"] = "hero without any EXIF metadata (must not fabricate settings)"

    _save(hero(), out / "P9260009.JPG", _exif("2026:09:26 10:10:00", orientation=6), rotate_for_orientation6=True)
    made["P9260009.JPG"] = "hero stored rotated with EXIF Orientation=6"

    _save(hero(), out / "P9260010.JPG", _exif("2026:09:26 10:11:00"))
    (out / "P9260010.ORF").write_bytes(b"IIRO\x08\x00\x00\x00" + b"SYNTHETIC-PLACEHOLDER-NOT-A-REAL-RAW" * 4000)
    made["P9260010.JPG"] = "JPEG half of a RAW+JPEG pair"
    made["P9260010.ORF"] = "FAKE RAW placeholder (undecodable) to exercise pairing + unsupported-RAW fallback"

    (out / "P9260002_copy.JPG").write_bytes((out / "P9260002.JPG").read_bytes())
    made["P9260002_copy.JPG"] = "byte-identical duplicate of P9260002.JPG"
    return made


def main(out: str | None = None) -> None:
    root = Path(__file__).resolve().parents[2] / "fixtures"
    target = Path(out) if out else root / "generated"
    made = generate(target)
    print(json.dumps({"out": str(target), "files": made}, indent=2))


if __name__ == "__main__":
    main()
