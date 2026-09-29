"""The camera driver: the only module that talks to libgphoto2 (python-gphoto2), plus a fake of the same shape.

Every call blocks, and libgphoto2 isn't thread-safe, so a driver is only ever used from the camera worker thread
(camera/service.py). Findings the driver relies on come from the spike (branch spike/camera-control):
- connect ≈ 2.7 s (libgphoto2 switches the camera to PC mode); settings 15–85 ms; reads ~2 ms;
- live view by ``capture_preview`` ≈ 15 fps, 1024×768 JPEG;
- a photo shows up as ``FILE_ADDED`` (after Olympus event 0xC102); the first of a connection is slow because
  libgphoto2 lists the card once;
- reading the whole config tree segfaults on prop d405, so only single named configs are read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class CameraAbsent(Exception):
    """No camera on USB (or it's off / asleep)."""


class CameraBusy(Exception):
    """A camera is there but another program (usually OM Capture) holds it."""


class CameraLost(Exception):
    """The connection dropped while in use (cable, sleep, battery)."""


@dataclass
class DriverEvent:
    kind: str  # timeout | file_added | ptp | prop | other
    folder: str | None = None
    name: str | None = None
    code: int | None = None
    param1: int | None = None
    prop: str | None = None
    raw: str = ""


class Driver(Protocol):
    model: str

    def connect(self) -> None: ...
    def close(self) -> None: ...
    def get(self, name: str) -> str: ...
    def choices(self, name: str) -> list[str]: ...
    def set(self, name: str, value: str) -> None: ...
    def trigger(self) -> None: ...
    def preview(self) -> bytes: ...
    def wait_event(self, timeout_ms: int) -> DriverEvent: ...
    def download(self, folder: str, name: str) -> bytes: ...
    def battery(self) -> int | None: ...


_PTP_EVENT = re.compile(r"PTP Event ([0-9a-fA-F]{4}), Param1 ([0-9a-fA-F]{8})")
_PTP_PROP = re.compile(r"PTP Property ([0-9a-fA-F]{4}) changed")


def parse_unknown(data: str) -> DriverEvent:
    """libgphoto2 reports vendor events as text: "PTP Event c101, Param1 00000000" / "PTP Property d01c changed…"."""
    m = _PTP_EVENT.search(data)
    if m:
        return DriverEvent("ptp", code=int(m.group(1), 16), param1=int(m.group(2), 16), raw=data)
    m = _PTP_PROP.search(data)
    if m:
        return DriverEvent("prop", prop=m.group(1).lower(), raw=data)
    return DriverEvent("other", raw=data)


class GPhotoDriver:
    """The real camera over USB."""

    def __init__(self) -> None:
        import gphoto2 as gp

        self.gp = gp
        self.camera = None
        self.model = "camera"
        self.handback: str | None = None

    def connect(self) -> None:
        gp = self.gp
        cam = gp.Camera()
        try:
            cam.init()
        except gp.GPhoto2Error as exc:
            if exc.code == gp.GP_ERROR_MODEL_NOT_FOUND:
                raise CameraAbsent("no camera on USB") from exc
            if exc.code in (gp.GP_ERROR_IO_USB_CLAIM, gp.GP_ERROR_IO_LOCK):
                raise CameraBusy("another app (OM Capture?) has the camera") from exc
            raise CameraAbsent(str(exc)) from exc
        self.camera = cam
        try:
            self.model = cam.get_abilities().model
        except Exception:
            self.model = "camera"

    # The spike left the body locked (its own buttons dead) until the cable was pulled, because libgphoto2 puts
    # the camera in PC mode (prop 0xD052) on connect and exit() doesn't switch it back. Setting d052 to 0 is the
    # likely hand-back; unverified until the owner session (docs/plans/camera-control.md, task 3).
    HANDBACK_PROP = "d052"

    def close(self) -> None:
        if self.camera is not None:
            self.handback = self._hand_back()
            try:
                self.camera.exit()
            except Exception:
                pass
            self.camera = None

    def _hand_back(self) -> str:
        try:
            w = self.camera.get_single_config(self.HANDBACK_PROP)
            before = w.get_value()
            for v in (0, "0"):
                try:
                    w.set_value(v)
                    self.camera.set_single_config(self.HANDBACK_PROP, w)
                    return f"{self.HANDBACK_PROP}: {before} → {v}"
                except Exception:
                    continue
            return f"{self.HANDBACK_PROP}: {before} (couldn't set 0)"
        except Exception as exc:
            return f"{self.HANDBACK_PROP} not available ({exc})"

    def _call(self, fn, *args):
        if self.camera is None:
            raise CameraLost("not connected")
        try:
            return fn(*args)
        except self.gp.GPhoto2Error as exc:
            if exc.code in (self.gp.GP_ERROR_IO, self.gp.GP_ERROR_IO_USB_FIND, self.gp.GP_ERROR_IO_READ,
                            self.gp.GP_ERROR_IO_WRITE, self.gp.GP_ERROR_MODEL_NOT_FOUND, self.gp.GP_ERROR_TIMEOUT):
                raise CameraLost(str(exc)) from exc
            raise

    def get(self, name: str) -> str:
        return str(self._call(lambda: self.camera.get_single_config(name).get_value()))

    def choices(self, name: str) -> list[str]:
        def f():
            w = self.camera.get_single_config(name)
            return [w.get_choice(i) for i in range(w.count_choices())]
        return self._call(f)

    def set(self, name: str, value: str) -> None:
        def f():
            w = self.camera.get_single_config(name)
            w.set_value(value)
            self.camera.set_single_config(name, w)
        self._call(f)

    def trigger(self) -> None:
        self._call(lambda: self.camera.trigger_capture())

    def preview(self) -> bytes:
        return bytes(self._call(lambda: self.camera.capture_preview().get_data_and_size()))

    def wait_event(self, timeout_ms: int) -> DriverEvent:
        gp = self.gp
        typ, data = self._call(lambda: self.camera.wait_for_event(timeout_ms))
        if typ == gp.GP_EVENT_TIMEOUT:
            return DriverEvent("timeout")
        if typ == gp.GP_EVENT_FILE_ADDED:
            return DriverEvent("file_added", folder=data.folder, name=data.name, raw=f"{data.folder}/{data.name}")
        if typ == gp.GP_EVENT_UNKNOWN and isinstance(data, str):
            return parse_unknown(data)
        return DriverEvent("other", raw=str(data))

    def download(self, folder: str, name: str) -> bytes:
        gp = self.gp
        return bytes(self._call(lambda: self.camera.file_get(folder, name, gp.GP_FILE_TYPE_NORMAL).get_data_and_size()))

    def battery(self) -> int | None:
        try:
            return int(self.get("5001"))
        except Exception:
            return None


# --- a simulated E-M1 II, for tests and demos (APERTURE_ALLY_CAMERA=mock) -------------------------------

APERTURES = ["1.0", "1.1", "1.2", "1.4", "1.6", "1.8", "2.0", "2.2", "2.5", "2.8", "3.2", "3.5", "4.0", "4.5",
             "5.0", "5.6", "6.3", "7.1", "8.0", "9.0", "10.0", "11.0", "13.0", "14.0", "16.0", "18.0", "20.0", "22.0"]
COMPENSATION = [f"{v / 3:.1f}" for v in range(-15, 16)]
ISOS = ["Auto", "64", "100", "125", "160", "200", "250", "320", "400", "500", "640", "800", "1000", "1250", "1600",
        "2000", "2500", "3200", "4000", "5000", "6400", "8000", "10000", "12800", "16000", "20000", "25600"]


@dataclass
class FakeDriver:
    """In-memory camera. ``lens`` limits the aperture like a real lens (the body accepts, then clamps)."""

    present: bool = True
    busy: bool = False
    lens: tuple[float, float] = (1.8, 22.0)
    jpeg: bytes = b"\xff\xd8fake-jpeg\xff\xd9"
    model: str = "Olympus E-M1MarkII (simulated)"
    values: dict[str, str] = field(default_factory=lambda: {
        "aperture": "5.6", "exposurecompensation": "0.0", "iso": "Auto", "shutterspeed": "1/125"})
    events: list[DriverEvent] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    connected: bool = False
    fail_next: str | None = None  # "lost" makes the next call raise CameraLost
    raw: bool = True  # shoot JPEG+ORF (tests); mock mode shoots JPEG only (a fake ORF would stall ingest)
    log: list[str] = field(default_factory=list)
    shot: int = 0

    def connect(self) -> None:
        if not self.present:
            raise CameraAbsent("no camera on USB")
        if self.busy:
            raise CameraBusy("another app (OM Capture?) has the camera")
        self.connected = True
        self.log.append("connect")

    def close(self) -> None:
        self.connected = False
        self.log.append("close")

    def _check(self) -> None:
        if self.fail_next == "lost" or not self.present:
            self.fail_next = None
            self.connected = False
            raise CameraLost("USB disconnected")
        if not self.connected:
            raise CameraLost("not connected")

    def get(self, name: str) -> str:
        self._check()
        return self.values[name]

    def choices(self, name: str) -> list[str]:
        self._check()
        return {"aperture": APERTURES, "exposurecompensation": COMPENSATION, "iso": ISOS}.get(name, [])

    def set(self, name: str, value: str) -> None:
        self._check()
        if name == "aperture":
            lo, hi = self.lens
            value = f"{min(max(float(value), lo), hi):.1f}"
        self.values[name] = value
        self.log.append(f"set {name}={value}")

    def trigger(self) -> None:
        self._check()
        self.shot += 1
        stem = f"_929{self.shot:04d}"
        self.files[f"/store_00010001/DCIM/100OLYMP/{stem}.JPG"] = self.jpeg
        folder = "/store_00010001/DCIM/100OLYMP"
        self.events += [DriverEvent("ptp", code=0xC101), DriverEvent("file_added", folder, f"{stem}.JPG")]
        if self.raw:
            self.files[f"{folder}/{stem}.ORF"] = b"fake-orf"
            self.events.append(DriverEvent("file_added", folder, f"{stem}.ORF"))
        self.log.append("trigger")

    def preview(self) -> bytes:
        self._check()
        return self.jpeg

    def wait_event(self, timeout_ms: int) -> DriverEvent:
        self._check()
        return self.events.pop(0) if self.events else DriverEvent("timeout")

    def download(self, folder: str, name: str) -> bytes:
        self._check()
        return self.files[f"{folder}/{name}"]

    def battery(self) -> int | None:
        return 100


def simulated_jpeg(text: str = "SIMULATED CAMERA", size: tuple[int, int] = (1024, 768)) -> bytes:
    """A plain grey frame labelled as simulated, for mock mode's live view and photos (never mistaken for real)."""
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, (96, 96, 96))
    d = ImageDraw.Draw(img)
    for x in range(0, size[0], 64):
        d.line([(x, 0), (x, size[1])], fill=(104, 104, 104))
    d.text((24, 24), text, fill=(235, 235, 235))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def default_driver(kind: str) -> Driver:
    return FakeDriver() if kind == "mock" else GPhotoDriver()


def is_jpeg(name: str) -> bool:
    return Path(name).suffix.lower() in (".jpg", ".jpeg")
