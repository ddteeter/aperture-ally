"""Optional RAW handling via rawpy/LibRaw.

Strategy for RAW-only captures: use the embedded JPEG preview if it is large enough, otherwise develop a
half-size sRGB preview. Unsupported/corrupt RAW raises ``RawUnsupported``; the app stays usable with
JPEG or manual import. Originals are never modified.
"""

from __future__ import annotations

import io
from pathlib import Path

RAW_EXTENSIONS = {".orf", ".ori", ".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".rw2"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}
OTHER_RASTER = {".png", ".tif", ".tiff"}


class RawUnsupported(Exception):
    pass


def is_raw(path: Path) -> bool:
    return path.suffix.lower() in RAW_EXTENSIONS


def is_primary_image(path: Path) -> bool:
    return path.suffix.lower() in JPEG_EXTENSIONS | OTHER_RASTER


def rawpy_available() -> bool:
    try:
        import rawpy  # noqa: F401
    except Exception:
        return False
    return True


def verify_raw(path: Path) -> None:
    """Cheap validity check: LibRaw can open and unpack the header."""
    try:
        import rawpy

        with rawpy.imread(str(path)) as raw:
            _ = raw.sizes
    except Exception as exc:
        raise RawUnsupported(f"{path.name}: {exc}") from exc


def make_preview(path: Path, out: Path, min_long_edge: int = 1000) -> str:
    """Write an sRGB JPEG preview for ``path``; returns 'raw_embedded' or 'raw_developed'."""
    try:
        import rawpy
        from PIL import Image
    except Exception as exc:
        raise RawUnsupported(f"rawpy unavailable: {exc}") from exc
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with rawpy.imread(str(path)) as raw:
            try:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    with Image.open(io.BytesIO(thumb.data)) as im:
                        im.load()
                        if max(im.size) >= min_long_edge:
                            out.write_bytes(thumb.data)
                            return "raw_embedded"
            except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
                pass
            rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8,
                                  output_color=rawpy.ColorSpace.sRGB)
            Image.fromarray(rgb).save(out, "JPEG", quality=90)
            return "raw_developed"
    except RawUnsupported:
        raise
    except Exception as exc:
        raise RawUnsupported(f"{path.name}: {exc}") from exc
