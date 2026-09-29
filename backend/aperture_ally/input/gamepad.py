"""Push-to-talk from a Bluetooth gamepad (8BitDo Micro in S mode, which presents as a Switch Pro Controller).

Why a gamepad and not keyboard mode: in S mode the Micro isn't a keyboard, so its buttons never type into
OM Capture, macOS needs no Input Monitoring permission to read it, and a held button arrives as exactly one
press and one release (no auto-repeat). Verified on the owner's Mac (docs/local-verification-results.md).

Reports are read with hidapi in a thread and decoded into button names that feed the same PTTKeyTracker as
the keyboard listener, so press/hold/release, pause and cancel behave identically. When the controller
sleeps or disconnects the listener reconnects by itself; a disconnect while talk is held fails closed.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .global_keys import KeySpec, PTTKeyTracker

log = logging.getLogger(__name__)

# Nintendo Switch Pro Controller ids (what the Micro reports in S mode).
SWITCH_PRO = (0x057E, 0x2009)

# Simple HID report 0x3F: byte 1 and 2 are button bits.
_BYTE1 = {0x01: "b", 0x02: "a", 0x04: "y", 0x08: "x", 0x10: "l", 0x20: "r", 0x40: "zl", 0x80: "zr"}
_BYTE2 = {0x01: "minus", 0x02: "plus", 0x04: "lstick", 0x08: "rstick", 0x10: "home", 0x20: "capture"}
# The Micro reports its D-pad as the left stick (byte 5 = X high byte, byte 7 = Y high byte, 0x80 centre);
# other pads use the hat in byte 3 (0 = up, clockwise, 8 = centred).
_HAT = {0: {"up"}, 1: {"up", "right"}, 2: {"right"}, 3: {"down", "right"}, 4: {"down"}, 5: {"down", "left"},
        6: {"left"}, 7: {"up", "left"}}

BUTTONS = sorted(set(_BYTE1.values()) | set(_BYTE2.values()) | {"up", "down", "left", "right"})


def decode_report(r: list[int] | bytes) -> set[str] | None:
    """Pressed button names in a Switch Pro simple report, or None for other report types."""
    if len(r) < 8 or r[0] != 0x3F:
        return None
    pressed = {n for bit, n in _BYTE1.items() if r[1] & bit} | {n for bit, n in _BYTE2.items() if r[2] & bit}
    pressed |= _HAT.get(r[3], set())
    x, y = r[5], r[7]
    if y < 0x40:
        pressed.add("up")
    elif y > 0xC0:
        pressed.add("down")
    if x < 0x40:
        pressed.add("left")
    elif x > 0xC0:
        pressed.add("right")
    return pressed


def _open_hid(vid: int, pid: int):
    import hid

    d = hid.device()
    d.open(vid, pid)
    return d


class GamepadListener:
    """Same interface as GlobalKeyListener (tracker, start/stop, learn, diagnostics, running, error)."""

    RECONNECT_S = 2.0

    def __init__(self, ptt_button: str, cancel_button: str | None, mode: str,
                 dispatch: Callable[[str], Awaitable[None]], on_failure: Callable[[str], Awaitable[None]],
                 pause_button: str | None = None, *, ids: tuple[int, int] = SWITCH_PRO, open_device=None,
                 on_button: Callable[[str, bool], Awaitable[None]] | None = None):
        self.tracker = PTTKeyTracker(KeySpec.parse(ptt_button), KeySpec.parse(cancel_button) if cancel_button else None,
                                     mode, KeySpec.parse(pause_button) if pause_button else None)
        self.dispatch, self.on_failure = dispatch, on_failure
        self.on_button = on_button  # every press/release too (camera buttons: camera/remote.py)
        self.ids = ids
        self._open = open_device or _open_hid
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._pressed: set[str] = set()
        self.running = False
        self.connected = False
        self.error: str | None = None
        self.reconnects = 0

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self.running = True
        threading.Thread(target=self._run, daemon=True, name="gamepad").start()

    def stop(self) -> None:
        self.running = False

    def learn(self) -> None:
        with self._lock:
            self.tracker.learned = None
            self.tracker.learn_waiting = True

    # --- the reader thread -------------------------------------------------------------------
    def _run(self) -> None:
        first = True
        while self.running:
            try:
                dev = self._open(*self.ids)
            except Exception as exc:
                self.connected = False
                self.error = f"controller not connected ({exc}); in S mode and paired?"
                time.sleep(self.RECONNECT_S)
                continue
            if not first:
                self.reconnects += 1
            first = False
            self.connected, self.error = True, None
            try:
                self._read(dev)
            except Exception as exc:
                log.info("gamepad disconnected: %s", exc)
                self.error = f"controller disconnected ({exc})"
            finally:
                self.connected = False
                try:
                    dev.close()
                except Exception:
                    pass
                self._release_all()

    def _read(self, dev) -> None:
        while self.running:
            r = dev.read(64, 250)  # timeout in ms; [] when nothing arrived
            if not r:
                continue
            pressed = decode_report(r)
            if pressed is not None:
                self.feed(pressed)

    def feed(self, pressed: set[str]) -> None:
        """Turn a new button state into press/release events (public for tests)."""
        now = time.monotonic()
        actions = []
        with self._lock:
            down, up = sorted(pressed - self._pressed), sorted(self._pressed - pressed)
            for name in down:
                actions.append(self.tracker.on_press(name, now))
            for name in up:
                actions.append(self.tracker.on_release(name, now))
            self._pressed = set(pressed)
        for a in actions:
            if a:
                self._emit(a)
        if self.on_button and self._loop and not self._loop.is_closed():
            for name, is_down in [(n, True) for n in down] + [(n, False) for n in up]:
                asyncio.run_coroutine_threadsafe(self.on_button(name, is_down), self._loop)

    def _release_all(self) -> None:
        """A disconnect while talk is held: fail closed (the recording is discarded, not sent)."""
        held = self.tracker.down_since is not None
        with self._lock:
            self._pressed = set()
            self.tracker.down_since = None
        if held and self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.on_failure("controller disconnected while talk was held"),
                                             self._loop)

    def _emit(self, action: str) -> None:
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.dispatch(action), self._loop)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "source": "gamepad",
            "connected": self.connected,
            "reconnects": self.reconnects,
            "error": self.error,
            "ptt_key": self.tracker.ptt.key,
            "mode": self.tracker.mode,
            "held": self.tracker.down_since is not None,
            "events": list(self.tracker.log),
            "learn_waiting": self.tracker.learn_waiting,
            "learned": self.tracker.learned,
        }
