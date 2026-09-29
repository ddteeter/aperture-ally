"""Tiny persistent-connection helper around python-gphoto2 for the Olympus E-M1 II spike.

Spike quality: no retries beyond what the measurements need, everything logged with
monotonic timestamps so latencies can be read straight off the log.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import gphoto2 as gp

T0 = time.monotonic()

# Olympus OM-D PTP event codes (libgphoto2 camlibs/ptp2/ptp.h)
EVENT_NAMES = {
    0x4002: "ObjectAdded",
    0x400D: "CaptureComplete",
    0xC101: "Olympus_CreateRecView_New",
    0xC102: "Olympus_ObjectAdded_New",
    0xC103: "Olympus_AF_Frame_New",
    0xC104: "Olympus_DirectStoreImage_New",
    0xC105: "Olympus_ComplateCameraControlOff_New",
    0xC106: "Olympus_AF_Frame_Over_Info_New",
    0xC108: "Olympus_DevicePropChanged_New",
    0xC10C: "Olympus_ImageTransferModeFinish_New",
    0xC10D: "Olympus_ImageRecordFinish_New",
    0xC10E: "Olympus_SlotStatusChange_New",
    0xC10F: "Olympus_PrioritizeRecord_New",
}

GP_EVENT_NAMES = {
    gp.GP_EVENT_UNKNOWN: "UNKNOWN",
    gp.GP_EVENT_TIMEOUT: "TIMEOUT",
    gp.GP_EVENT_FILE_ADDED: "FILE_ADDED",
    gp.GP_EVENT_FOLDER_ADDED: "FOLDER_ADDED",
    gp.GP_EVENT_CAPTURE_COMPLETE: "CAPTURE_COMPLETE",
    gp.GP_EVENT_FILE_CHANGED: "FILE_CHANGED",
}

# Settings the spike reads, changes and restores (config names as libgphoto2 exposes them).
SETTINGS = ["aperture", "shutterspeed", "iso", "exposurecompensation", "focusmode", "imageformat"]
# Raw Olympus OM-D props worth watching (hex without 0x -> meaning per libgphoto2 ptp.h)
RAW_PROPS = {
    "d009": "OMD_DriveMode",
    "d0dc": "CaptureTarget",
    "d110": "AEBracketingFrame(?)",
    "d111": "AEBracketingStep(?)",
}

_PTP_EVENT_RE = re.compile(r"PTP Event ([0-9a-fA-F]{4}), Param1 ([0-9a-fA-F]{8})")


def now() -> float:
    return time.monotonic() - T0


def scratch_dir() -> Path:
    base = Path(os.environ.get("TMPDIR", "/tmp")) / "camera-spike"
    base.mkdir(parents=True, exist_ok=True)
    return base


class Log:
    """Print + JSONL log of everything that happens."""

    def __init__(self, path: Path):
        self.path = path
        self.f = path.open("a")

    def __call__(self, kind: str, **kw):
        rec = {"t": round(now(), 4), "kind": kind, **kw}
        self.f.write(json.dumps(rec, default=str) + "\n")
        self.f.flush()
        extra = " ".join(f"{k}={v}" for k, v in kw.items())
        print(f"[{rec['t']:9.3f}] {kind} {extra}", flush=True)


@dataclass
class Event:
    t: float
    gp_type: str
    raw: object
    ptp_code: int | None = None
    param1: int | None = None
    path: tuple[str, str] | None = None

    @property
    def name(self) -> str:
        if self.ptp_code is not None:
            return EVENT_NAMES.get(self.ptp_code, f"0x{self.ptp_code:04X}")
        return self.gp_type


@dataclass
class Cam:
    log: Log
    camera: gp.Camera = field(default_factory=gp.Camera)
    connect_s: float = 0.0

    def connect(self) -> float:
        t = time.monotonic()
        self.camera.init()
        self.connect_s = time.monotonic() - t
        self.log("connected", seconds=round(self.connect_s, 3))
        return self.connect_s

    def close(self):
        try:
            self.camera.exit()
        except gp.GPhoto2Error as e:
            self.log("close_error", error=str(e))

    # ---- config -------------------------------------------------------
    def get(self, name: str) -> str:
        w = self.camera.get_single_config(name)
        return w.get_value()

    def choices(self, name: str) -> list[str]:
        w = self.camera.get_single_config(name)
        return [w.get_choice(i) for i in range(w.count_choices())]

    def set(self, name: str, value) -> float:
        t = time.monotonic()
        w = self.camera.get_single_config(name)
        w.set_value(value)
        self.camera.set_single_config(name, w)
        return time.monotonic() - t

    def battery(self) -> int:
        return int(self.get("5001"))

    # ---- events -------------------------------------------------------
    def wait_event(self, timeout_ms: int) -> Event:
        typ, data = self.camera.wait_for_event(timeout_ms)
        ev = Event(t=now(), gp_type=GP_EVENT_NAMES.get(typ, str(typ)), raw=data)
        if typ == gp.GP_EVENT_UNKNOWN and isinstance(data, str):
            m = _PTP_EVENT_RE.search(data)
            if m:
                ev.ptp_code = int(m.group(1), 16)
                ev.param1 = int(m.group(2), 16)
        elif typ in (gp.GP_EVENT_FILE_ADDED, gp.GP_EVENT_FOLDER_ADDED, gp.GP_EVENT_FILE_CHANGED):
            ev.path = (data.folder, data.name)
            ev.raw = f"{data.folder}/{data.name}"
        return ev

    def drain(self, seconds: float = 1.0) -> list[Event]:
        """Consume pending events for `seconds`, logging them."""
        out = []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ev = self.wait_event(100)
            if ev.gp_type == "TIMEOUT":
                continue
            self.log_event(ev, "drain")
            out.append(ev)
        return out

    def log_event(self, ev: Event, ctx: str = ""):
        self.log(
            "event",
            ctx=ctx,
            name=ev.name,
            gp=ev.gp_type,
            code=f"0x{ev.ptp_code:04X}" if ev.ptp_code is not None else None,
            param1=f"0x{ev.param1:08X}" if ev.param1 is not None else None,
            raw=ev.raw,
        )

    # ---- files --------------------------------------------------------
    def download(self, folder: str, name: str, dest: Path) -> tuple[int, float]:
        t = time.monotonic()
        f = self.camera.file_get(folder, name, gp.GP_FILE_TYPE_NORMAL)
        f.save(str(dest))
        return dest.stat().st_size, time.monotonic() - t

    def trigger(self) -> float:
        t = time.monotonic()
        self.camera.trigger_capture()
        return time.monotonic() - t


# ---- shutter budget (spike rule: <= 10 fires in total) -----------------------
SHUTTER_BUDGET = 10


def spend_shutter(log: Log) -> int:
    """Count a shutter actuation in the scratch dir; refuse beyond the budget."""
    p = scratch_dir() / "shutter_count.txt"
    n = int(p.read_text()) if p.exists() else 0
    if n >= SHUTTER_BUDGET:
        raise SystemExit(f"shutter budget exhausted ({n}/{SHUTTER_BUDGET})")
    p.write_text(str(n + 1))
    log("shutter_budget", used=n + 1, budget=SHUTTER_BUDGET)
    return n + 1


def snapshot_props(cam: Cam) -> dict[str, str]:
    """All /other raw PTP props (skipping d405, whose NULL text value segfaults get_value)."""
    cfg = cam.camera.get_config()
    other = cfg.get_child_by_name("other")
    vals = {}
    for c in other.get_children():
        n = c.get_name()
        if n in ("d405",):
            continue
        vals[n] = c.get_value()
    return vals


# ---- event pump: react to events, download immediately ------------------------
@dataclass
class Download:
    t_event: float  # when FILE_ADDED arrived
    t_done: float
    camera_path: str
    local: Path
    size: int
    seconds: float


@dataclass
class Pump:
    """Polls wait_for_event and downloads every FILE_ADDED immediately under a unique name."""

    cam: Cam
    dest: Path
    prefix: str = "shot"
    seq: int = 0
    events: list[Event] = field(default_factory=list)
    downloads: list[Download] = field(default_factory=list)
    poll_ms: int = 20

    def step(self, timeout_ms: int | None = None) -> Event | None:
        ev = self.cam.wait_event(self.poll_ms if timeout_ms is None else timeout_ms)
        if ev.gp_type == "TIMEOUT":
            return None
        self.events.append(ev)
        self.cam.log_event(ev, "pump")
        if ev.gp_type == "FILE_ADDED" and ev.path:
            folder, name = ev.path
            ext = Path(name).suffix.lower() or ".bin"
            self.seq += 1
            local = self.dest / f"{self.prefix}_{self.seq:03d}{ext}"
            try:
                size, secs = self.cam.download(folder, name, local)
            except Exception as e:  # noqa: BLE001
                self.cam.log("download_error", path=f"{folder}/{name}", error=str(e))
                return ev
            d = Download(ev.t, now(), f"{folder}/{name}", local, size, secs)
            self.downloads.append(d)
            self.cam.log("downloaded", camera=d.camera_path, local=local.name, kb=size // 1024,
                         ms=round(secs * 1000, 1), since_event_ms=round((d.t_done - ev.t) * 1000, 1))
        return ev

    def run_for(self, seconds: float):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.step()
