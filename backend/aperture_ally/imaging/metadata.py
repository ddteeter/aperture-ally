"""Camera metadata extraction and normalization.

Preferred path: one long-lived ``exiftool -stay_open`` process with JSON numeric output (handles ORF
and Olympus maker notes). Fallback: Pillow EXIF for JPEGs when ExifTool is not installed. The
normalized dict never invents values: a missing tag stays absent/None.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

EXPOSURE_PROGRAMS = {0: "unknown", 1: "manual", 2: "program", 3: "aperture_priority", 4: "shutter_priority",
                     5: "program", 6: "program", 7: "program", 8: "program"}


class ExifToolProcess:
    """Managed ``exiftool -stay_open True -@ -`` process. Thread-safe; restarts after failure."""

    SENTINEL = "{ready}"

    def __init__(self, executable: str | None = None):
        self.executable = executable or shutil.which("exiftool")
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.executable is not None

    def version(self) -> str | None:
        if not self.available:
            return None
        try:
            return subprocess.run([self.executable, "-ver"], capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return None

    def _start(self) -> subprocess.Popen[str]:
        assert self.executable
        return subprocess.Popen(
            [self.executable, "-stay_open", "True", "-@", "-", "-common_args", "-json", "-n", "-G0:1", "-a"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )

    def read(self, path: Path) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("exiftool not installed")
        with self._lock:
            for attempt in (1, 2):
                if self._proc is None or self._proc.poll() is not None:
                    self._proc = self._start()
                try:
                    assert self._proc.stdin and self._proc.stdout
                    self._proc.stdin.write(f"{path}\n-execute\n")
                    self._proc.stdin.flush()
                    lines = []
                    while True:
                        line = self._proc.stdout.readline()
                        if line == "":
                            raise RuntimeError("exiftool exited")
                        if line.strip() == self.SENTINEL:
                            break
                        lines.append(line)
                    data = json.loads("".join(lines) or "[{}]")
                    return data[0] if data else {}
                except Exception:
                    self.close()
                    if attempt == 2:
                        raise
        return {}

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                assert self._proc.stdin
                self._proc.stdin.write("-stay_open\nFalse\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()
        self._proc = None


def _first(raw: dict[str, Any], *names: str) -> Any:
    """Find a tag by bare name regardless of ExifTool group prefix (``EXIF:ExifIFD:FNumber``)."""
    for name in names:
        for k, v in raw.items():
            if k == name or k.endswith(":" + name):
                if v not in (None, "", "undef"):
                    return v
    return None


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _parse_dt(dt: Any, subsec: Any = None) -> str | None:
    if not dt or not isinstance(dt, str):
        return None
    try:
        parsed = datetime.strptime(dt[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    iso = parsed.isoformat()
    if subsec not in (None, ""):
        iso += "." + str(subsec).strip()[:3].ljust(3, "0")
    return iso  # camera-local time; the camera clock's zone is unknown


def normalize(raw: dict[str, Any], source: str) -> dict[str, Any]:
    flash = _first(raw, "Flash")
    program = _first(raw, "ExposureProgram")
    exposure_mode_tag = _first(raw, "ExposureMode")
    out: dict[str, Any] = {
        "source": source,
        "camera_make": _first(raw, "Make"),
        "camera_model": _first(raw, "Model"),
        "lens": _first(raw, "LensModel", "LensType", "Lens"),
        "exposure_time_s": _num(_first(raw, "ExposureTime")),
        "f_number": _num(_first(raw, "FNumber", "Aperture")),
        "iso": _num(_first(raw, "ISO", "PhotographicSensitivity", "ISOSpeedRatings")),
        "focal_length_mm": _num(_first(raw, "FocalLength")),
        "focal_length_35mm": _num(_first(raw, "FocalLengthIn35mmFormat")),
        "exposure_compensation_ev": _first(raw, "ExposureCompensation"),
        "flash_fired": (bool(int(flash) & 1) if isinstance(flash, int | float) else None),
        "exposure_program": EXPOSURE_PROGRAMS.get(int(program), "unknown") if isinstance(program, int | float) else None,
        "exposure_mode_manual": (int(exposure_mode_tag) == 1) if isinstance(exposure_mode_tag, int | float) else None,
        "datetime_original": _parse_dt(_first(raw, "DateTimeOriginal"), _first(raw, "SubSecTimeOriginal")),
        "orientation": _first(raw, "Orientation"),
        "raw_width": _first(raw, "ImageWidth", "ExifImageWidth"),
        "raw_height": _first(raw, "ImageHeight", "ExifImageHeight"),
        "color_space": _first(raw, "ColorSpace"),
    }
    out = {k: v for k, v in out.items() if v is not None}
    out["exposure_known"] = all(k in out for k in ("exposure_time_s", "f_number", "iso"))
    out["metadata_available"] = any(
        k in out for k in ("camera_model", "exposure_time_s", "f_number", "iso", "focal_length_mm")
    )
    return out


_PIL_TAGS = {
    271: "Make", 272: "Model", 274: "Orientation", 33434: "ExposureTime", 33437: "FNumber", 34850: "ExposureProgram",
    34855: "ISO", 36867: "DateTimeOriginal", 37521: "SubSecTimeOriginal", 37380: "ExposureCompensation",
    37385: "Flash", 37386: "FocalLength", 41986: "ExposureMode", 41989: "FocalLengthIn35mmFormat",
    42036: "LensModel", 40961: "ColorSpace",
}


def read_with_pillow(path: Path) -> dict[str, Any]:
    from PIL import Image

    raw: dict[str, Any] = {}
    with Image.open(path) as im:
        exif = im.getexif()
        merged = dict(exif)
        try:
            merged.update(exif.get_ifd(0x8769))
        except Exception:
            pass
        for tag, name in _PIL_TAGS.items():
            if tag in merged:
                v = merged[tag]
                if isinstance(v, tuple) and len(v) == 1:
                    v = v[0]
                try:
                    v = float(v) if not isinstance(v, str | bytes) else v
                except (TypeError, ValueError):
                    pass
                if isinstance(v, bytes):
                    v = v.decode(errors="ignore").strip("\x00 ")
                if isinstance(v, str):
                    v = v.strip("\x00 ")
                raw[name] = v
    return raw


class MetadataReader:
    def __init__(self, exiftool: ExifToolProcess | None = None):
        self.exiftool = exiftool or ExifToolProcess()

    def read(self, path: Path, include_raw: bool = False) -> dict[str, Any]:
        """Normalized metadata; with ``include_raw`` the full tag dict is added under ``_raw``."""
        if self.exiftool.available:
            try:
                raw = self.exiftool.read(path)
                return {**normalize(raw, "exiftool"), **({"_raw": raw} if include_raw else {})}
            except Exception as exc:
                log.warning("exiftool failed for %s: %s; falling back to Pillow", path, exc)
        try:
            raw = read_with_pillow(path)
            return {**normalize(raw, "pillow"), **({"_raw": {k: str(v) for k, v in raw.items()}} if include_raw else {})}
        except Exception as exc:
            return {"source": "none", "error": str(exc), "exposure_known": False, "metadata_available": False}

    def close(self) -> None:
        self.exiftool.close()
