"""CameraService: owns the camera on one worker thread and exposes it to the app (async) and the UI (bus events).

States: absent (no camera; looked for every ``camera_poll_s``) → connecting → connected ⇄ asleep (it dropped;
looked for again) · busy_elsewhere (OM Capture or another app holds it) · released (handed to OM Capture on
purpose; ``take`` gets it back) · off (camera control disabled).

Photos: every ``FILE_ADDED`` is downloaded at once into ``destination`` (the active shoot's watch folder),
written as ``.part`` and renamed, so the existing ingest picks it up exactly as it does OM Capture's files.
JPEG and ORF of one frame keep one stem, so they pair.
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any, cast

from . import settings as S
from .driver import CameraAbsent, CameraBusy, CameraLost, Driver, DriverEvent, is_jpeg

log = logging.getLogger(__name__)

PHOTO_TAKEN = 0xC101  # Olympus CreateRecView: the shutter fired
LIVE_FPS = 30.0  # a preview frame takes ~22 ms on the E-M1 II
# Checking for camera events costs ~290 ms on the E-M1 II whatever the timeout (libgphoto2 asks the camera), so
# during live view it runs about once a second, and every loop for a while after a shot (so files arrive fast).
LIVE_EVENT_EVERY_S = 1.0
EXPECT_FILES_S = 8.0
READBACK_S = 0.15  # the body reports a new value ~20 ms after a set; wait this long before calling it clamped


class NotConnected(RuntimeError):
    pass


class CameraService:
    def __init__(self, mode: str, driver_factory: Callable[[], Driver], publish: Callable[..., Any], *,
                 inbox: Path, poll_s: float = 2.0, destination_fn: Callable[[], Path | None] | None = None):
        self.mode = mode  # off | direct | mock
        self._factory = driver_factory
        self._publish = publish
        self.inbox = inbox
        self.destination: Path | None = None  # fixed destination (tests); else destination_fn, else the inbox
        self.destination_fn = destination_fn or (lambda: None)
        self.poll_s = poll_s
        self.state = "off" if mode == "off" else "absent"
        self.detail = "Camera control is off (APERTURE_ALLY_CAMERA=off)" if mode == "off" else "Looking for a camera on USB"
        self.model: str | None = None
        self.battery: int | None = None
        self.values: dict[str, str] = {}
        self.orders: dict[str, list[str]] = {}
        self.first_photo = True
        self.photos = 0
        self.last_command: str | None = None
        self.ever_connected = False
        self._driver: Driver | None = None
        self._cmds: queue.Queue[tuple[Callable[[], Any], Future]] = queue.Queue()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stems: dict[str, str] = {}  # camera stem -> local stem
        self._shutter_at: float | None = None
        self._refresh_due: float | None = None
        # live view: the newest frame; captured only while someone watches
        self.live_watchers = 0
        self.frame: bytes | None = None
        self.frame_seq = 0
        self._last_frame_at = 0.0
        self._last_event_poll = 0.0
        self._expect_until = 0.0  # poll events every loop until then (after a shutter)
        self.timing: dict[str, float] = {}  # rolling ms: preview, event wait (Diagnostics; tuning live view)

    # --- lifecycle ---------------------------------------------------------------------------
    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        if self.mode == "off" or self._thread:
            return
        self._loop = loop
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Release the camera (so its own buttons work again) and end the worker."""
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout)
            self._thread = None

    # --- async API (runs on the worker) --------------------------------------------------------
    async def _call(self, fn: Callable[[], Any], timeout: float = 15.0) -> Any:
        if self.mode == "off" or not self._thread:
            raise NotConnected(self.detail)
        fut: Future = Future()
        self._cmds.put((fn, fut))
        return await asyncio.wait_for(asyncio.wrap_future(fut), timeout)

    async def take(self) -> dict[str, Any]:
        def f():
            if self.state == "released":
                self._set_state("absent", "Looking for a camera on USB")
            return self.snapshot()
        return await self._call(f)

    async def release(self) -> dict[str, Any]:
        def f():
            self._disconnect("released", "Released to OM Capture. ⌘K takes it back.")
            return self.snapshot()
        return await self._call(f)

    async def step(self, setting: str, direction: int, source: str = "remote") -> dict[str, Any]:
        return await self._call(lambda: self._step(setting, direction, source))

    async def set_value(self, setting: str, value: str, source: str = "ui") -> dict[str, Any]:
        return await self._call(lambda: self._set(setting, value, source))

    async def trigger(self, source: str = "remote") -> dict[str, Any]:
        def f():
            d = self._require()
            self._shutter_at = time.monotonic()
            self._expect_until = self._shutter_at + EXPECT_FILES_S
            d.trigger()
            self.last_command = "shutter"
            return {"first_photo": self.first_photo}
        return await self._call(f)

    # --- debug probe (APERTURE_ALLY_CAMERA_DEBUG=true): read any property, set any property ---------
    async def list_props(self) -> list[dict[str, Any]]:
        return await self._call(lambda: self._require().list_config(), timeout=30)

    async def set_raw(self, name: str, value: str) -> dict[str, Any]:
        def f():
            d = self._require()
            before = d.get(name)
            d.set(name, value)
            time.sleep(0.1)
            after = d.get(name)
            self.last_command = f"debug {name}: {before} → {after}"
            return {"name": name, "before": before, "requested": value, "after": after}
        return await self._call(f)

    # --- snapshot for the API / UI -----------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "state": self.state, "detail": self.detail, "model": self.model,
            "battery": self.battery, "photos": self.photos, "first_photo_pending": self.first_photo,
            "live_watchers": self.live_watchers, "last_command": self.last_command, "timing": self.timing,
            "settings": {k: {"value": self.values.get(k), "display": S.display(k, self.values.get(k)),  # type: ignore[arg-type]
                             "order": self.orders.get(k, [])} for k in (*S.SETTINGS, *S.READ_ONLY)},
            "destination": str(self.current_destination()),
        }

    def current_destination(self) -> Path:
        """The active shoot's watch folder, so ingest takes the photo as usual; the inbox when no shoot is open."""
        return self.destination or self.destination_fn() or self.inbox

    # --- worker thread -------------------------------------------------------------------------
    def _run(self) -> None:
        next_try = 0.0
        while not self._stopping.is_set():
            if self._driver is None:
                self._drain_commands()
                if self.state not in ("released",) and time.monotonic() >= next_try:
                    self._try_connect()
                    next_try = time.monotonic() + self.poll_s
                if self._driver is None:
                    self._stopping.wait(0.05)
                continue
            try:
                if not self._drain_commands(one=True):
                    self._idle_work()
            except CameraLost as exc:
                self._disconnect("asleep", f"Camera disconnected or asleep ({exc}). Half-press the shutter to wake it.")
                next_try = time.monotonic() + self.poll_s
            except Exception:
                log.exception("camera worker error")
        self._disconnect("off" if self.mode == "off" else "absent", "Stopped")

    def _drain_commands(self, one: bool = False) -> bool:
        ran = False
        while True:
            try:
                fn, fut = self._cmds.get_nowait()
            except queue.Empty:
                return ran
            ran = True
            if fut.set_running_or_notify_cancel():
                try:
                    fut.set_result(fn())
                except CameraLost as exc:
                    fut.set_exception(NotConnected(str(exc)))
                    raise
                except Exception as exc:
                    fut.set_exception(exc)
            if one:
                return True

    def _try_connect(self) -> None:
        driver = self._factory()
        self._set_state("connecting", "Connecting to the camera…")
        t0 = time.monotonic()
        try:
            driver.connect()
        except CameraBusy as exc:
            self._set_state("busy_elsewhere", f"{exc}. Close OM Capture to control the camera from here.")
            return
        except CameraAbsent:
            if self.ever_connected:
                self._set_state("asleep", "Camera asleep or unplugged. Half-press the shutter to wake it.")
            else:
                self._set_state("absent", "Waiting for the camera. Plug in USB and switch it on.")
            return
        except Exception as exc:
            self._set_state("absent", f"Couldn't connect: {exc}")
            return
        self._driver = driver
        self.model = driver.model
        self.first_photo, self._stems = True, {}
        try:
            for k in S.SETTINGS:
                self.orders[k] = S.ordered(k, driver.choices(k))
                self.values[k] = driver.get(k)
            for k in S.READ_ONLY:
                self.values[k] = driver.get(k)
            self.battery = driver.battery()
        except CameraLost:
            self._disconnect("asleep", "Camera dropped while connecting")
            return
        self.ever_connected = True
        self._set_state("connected", f"{self.model} · USB · connected in {time.monotonic() - t0:.1f} s")

    def _disconnect(self, state: str, detail: str) -> None:
        if self._driver is not None:
            try:
                self._driver.close()
            except Exception:
                pass
            handback = getattr(self._driver, "handback", None)
            if handback:
                self._emit("camera.handback", result=handback, state=state)  # verify at the camera (plan, task 3)
            self._driver = None
        self.frame = None
        self._set_state(state, detail)

    def _require(self) -> Driver:
        if self._driver is None:
            raise NotConnected(self.detail)
        return self._driver

    def _idle_work(self) -> None:
        d = self._require()
        now = time.monotonic()
        if self.live_watchers > 0 and now - self._last_frame_at >= 1 / LIVE_FPS:
            t0 = time.monotonic()
            frame = d.preview()
            self._avg("preview_ms", (time.monotonic() - t0) * 1000)
            self._last_frame_at = now
            if frame.startswith(b"\xff\xd8"):  # never pass on a corrupt frame
                self.frame = frame
                self.frame_seq += 1
        if self._refresh_due is not None and now >= self._refresh_due:
            self._refresh_due = None
            self._refresh_values()
        live_quiet = self.live_watchers > 0 and now >= self._expect_until
        if live_quiet and now - self._last_event_poll < LIVE_EVENT_EVERY_S:
            wait = self._last_frame_at + 1 / LIVE_FPS - time.monotonic()
            time.sleep(min(max(wait, 0.002), 0.02))  # until the next frame is due; don't spin
            return
        t0 = time.monotonic()
        self._last_event_poll = t0
        ev = d.wait_event(10 if self.live_watchers else 50)
        self._avg("event_ms", (time.monotonic() - t0) * 1000)
        if ev.kind != "timeout":
            self._on_event(ev)

    def _avg(self, key: str, ms: float) -> None:
        prev = self.timing.get(key)
        self.timing[key] = round(ms if prev is None else prev * 0.8 + ms * 0.2, 1)

    def _on_event(self, ev: DriverEvent) -> None:
        if ev.kind == "ptp" and ev.code == PHOTO_TAKEN:
            self._shutter_at = self._shutter_at or time.monotonic()
            self._expect_until = time.monotonic() + EXPECT_FILES_S
            self._emit("camera.shutter", first_photo=self.first_photo)
        elif ev.kind == "prop":
            self._refresh_due = time.monotonic() + 0.1  # a dial turned on the body, or the metered shutter moved
        elif ev.kind == "file_added" and ev.folder and ev.name:
            self._download(ev.folder, ev.name)

    def _download(self, folder: str, name: str) -> None:
        t0 = time.monotonic()
        data = self._require().download(folder, name)
        dest = self.current_destination()
        dest.mkdir(parents=True, exist_ok=True)
        stem, ext = os.path.splitext(name)
        local = self._stems.get(stem)
        if local is None:
            base = stem.lstrip("_") or "photo"
            local, n = f"AA{base}", 1
            while any((dest / f"{local}{e}").exists() for e in (".JPG", ".ORF", ".jpg", ".orf")):
                n += 1
                local = f"AA{base}-{n}"
            self._stems[stem] = local
        final = dest / f"{local}{ext.upper()}"
        part = dest / f".{final.name}.part"
        part.write_bytes(data)
        os.replace(part, final)
        took_ms = round((time.monotonic() - t0) * 1000)
        since = round((time.monotonic() - self._shutter_at) * 1000) if self._shutter_at else None
        if is_jpeg(name):
            self.photos += 1
            first, self.first_photo = self.first_photo, False
            self._shutter_at = None
            self._emit("camera.photo", name=final.name, bytes=len(data), download_ms=took_ms, since_shutter_ms=since,
                       first_of_connection=first)
        else:
            self._emit("camera.photo.raw", name=final.name, bytes=len(data), download_ms=took_ms)

    def _refresh_values(self) -> None:
        d = self._require()
        for k in (*S.SETTINGS, *S.READ_ONLY):
            v = d.get(k)
            if v != self.values.get(k):
                self.values[k] = v
                self._emit("camera.setting", setting=k, value=v, display=S.display(k, v), source="camera", end=None)

    def _step(self, name: str, direction: int, source: str) -> dict[str, Any]:
        if name not in S.SETTINGS:
            raise ValueError(f"unknown setting {name}")
        setting = cast(S.Setting, name)
        d = self._require()
        cur = self.values.get(setting) or d.get(setting)
        target, at_end = S.step(cur, self.orders.get(setting, []), direction)
        actual = cur
        if not at_end:
            d.set(setting, target)
            actual = self._read_back(setting, cur)
            if S.index_of(actual, self.orders[setting]) == S.index_of(cur, self.orders[setting]):
                at_end = True  # the lens (or mode) clamped it: this is the end of the usable range
        self.values[setting] = actual
        self.last_command = f"{S.LABEL[setting]} {S.display(setting, cur)} → {S.display(setting, actual)}"
        end = S.end_word(setting, direction) if at_end else None
        out = {"setting": setting, "value": actual, "display": S.display(setting, actual), "end": end,
               "spoken": S.spoken(setting, actual, end=end), "source": source}
        self._emit("camera.setting", **out)
        return out

    def _set(self, name: str, value: str, source: str) -> dict[str, Any]:
        if name not in S.SETTINGS:
            raise ValueError(f"unknown setting {name}")
        setting = cast(S.Setting, name)
        d = self._require()
        order = self.orders.get(setting, [])
        i = S.index_of(value, order)
        if i is None:
            raise ValueError(f"{value} isn't a {setting} value this camera offers")
        cur = self.values.get(setting, "")
        d.set(setting, order[i])
        actual = self._read_back(setting, cur)
        self.values[setting] = actual
        clamped = S.index_of(actual, order) != i
        self.last_command = f"{S.LABEL[setting]} → {S.display(setting, actual)}"
        out = {"setting": setting, "value": actual, "display": S.display(setting, actual),
               "requested": order[i], "clamped": clamped, "source": source,
               "spoken": S.spoken(setting, actual), "end": None}
        self._emit("camera.setting", **out)
        return out

    def _read_back(self, setting: str, before: str) -> str:
        d = self._require()
        deadline = time.monotonic() + READBACK_S
        v = d.get(setting)
        while v == before and time.monotonic() < deadline:
            time.sleep(0.02)
            v = d.get(setting)
        return v

    # --- state + events --------------------------------------------------------------------------
    def _set_state(self, state: str, detail: str) -> None:
        changed = state != self.state
        self.state, self.detail = state, detail
        if changed:
            self._emit("camera.state", state=state, detail=detail, model=self.model)

    def _emit(self, type_: str, **payload: Any) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(lambda: self._publish(type_, **payload))
        else:
            self._publish(type_, **payload)
