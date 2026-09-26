"""Global push-to-talk key listener (pynput) for keyboard-style Bluetooth remotes.

Only the configured PTT/cancel keys are recorded in diagnostics (press, release, repeat, hold time);
all other keystrokes are ignored and never logged. "Learn" mode reports the *name* of the next single
key pressed, once, so a remote's key can be identified.

macOS requires Input Monitoring (and possibly Accessibility) permission for the process running the
backend (Terminal/iTerm). Validate on the target Mac: docs/hardware-checks.md.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

MODIFIERS = {"ctrl", "alt", "cmd", "shift"}


@dataclass(frozen=True)
class KeySpec:
    key: str
    modifiers: frozenset[str] = frozenset()

    @classmethod
    def parse(cls, spec: str) -> KeySpec:
        parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
        if not parts:
            raise ValueError("empty key spec")
        mods = frozenset(p for p in parts[:-1])
        bad = mods - MODIFIERS
        if bad:
            raise ValueError(f"unknown modifiers {bad}")
        return cls(parts[-1], mods)


def key_name(key: Any) -> str:
    """Normalize a pynput key to a spec name: 'f18', 'page_down', 'a', 'space'."""
    name = getattr(key, "name", None)
    if name:
        return str(name).lower()
    char = getattr(key, "char", None)
    if char:
        return char.lower()
    vk = getattr(key, "vk", None)
    return f"vk{vk}" if vk is not None else str(key).lower()


def modifier_of(name: str) -> str | None:
    for m in MODIFIERS:
        if name == m or name.startswith(m + "_"):
            return m
    return None


class PTTKeyTracker:
    """Pure key-state logic (testable without pynput): maps raw events to PTT actions."""

    def __init__(self, ptt: KeySpec, cancel: KeySpec | None, mode: str):
        self.ptt, self.cancel, self.mode = ptt, cancel, mode
        self.down_since: float | None = None
        self.mods: set[str] = set()
        self.log: deque[dict[str, Any]] = deque(maxlen=200)
        self.learn_waiting = False
        self.learned: str | None = None
        self.on_log = None  # optional callback(entry) — persisted telemetry; PTT/cancel keys only

    def on_press(self, name: str, now: float | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        if self.learn_waiting and modifier_of(name) is None:
            self.learn_waiting = False
            self.learned = "+".join(sorted(self.mods) + [name])
            return "learned"
        m = modifier_of(name)
        if m:
            self.mods.add(m)
            return None
        if self.cancel and name == self.cancel.key and self.cancel.modifiers <= self.mods:
            self._log("cancel", name, now)
            return "cancel"
        if name != self.ptt.key or not self.ptt.modifiers <= self.mods:
            return None
        if self.down_since is not None:
            self._log("repeat", name, now, hold_ms=(now - self.down_since) * 1000)
            return None  # OS auto-repeat while held
        self.down_since = now
        self._log("press", name, now)
        return "toggle" if self.mode == "toggle" else "press"

    def on_release(self, name: str, now: float | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        m = modifier_of(name)
        if m:
            self.mods.discard(m)
            return None
        if name != self.ptt.key or self.down_since is None:
            return None
        hold = (now - self.down_since) * 1000
        self.down_since = None
        self._log("release", name, now, hold_ms=hold)
        return None if self.mode == "toggle" else "release"

    def _log(self, kind: str, name: str, now: float, **extra: Any) -> None:
        entry = {"kind": kind, "key": name, "t": round(now, 4), **{k: round(v, 1) for k, v in extra.items()}}
        self.log.append(entry)
        if self.on_log:
            self.on_log(entry)


class GlobalKeyListener:
    def __init__(self, ptt_spec: str, cancel_spec: str | None, mode: str,
                 dispatch: Callable[[str], Awaitable[None]], on_failure: Callable[[str], Awaitable[None]]):
        self.tracker = PTTKeyTracker(KeySpec.parse(ptt_spec), KeySpec.parse(cancel_spec) if cancel_spec else None, mode)
        self.dispatch = dispatch
        self.on_failure = on_failure
        self._listener = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.error: str | None = None
        self.running = False
        self._lock = threading.Lock()

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        try:
            from pynput import keyboard
        except Exception as exc:
            self.error = f"pynput unavailable: {exc}"
            return
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._listener.daemon = True
        self._listener.start()
        self.running = True
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self) -> None:
        """Detect a dead listener thread and fail closed."""
        while self.running and self._listener is not None:
            time.sleep(1.0)
            if not self._listener.is_alive():
                self.running = False
                self.error = "global key listener stopped (permission revoked or backend error)"
                self._emit_failure(self.error)
                return

    def _emit(self, action: str) -> None:
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.dispatch(action), self._loop)

    def _emit_failure(self, err: str) -> None:
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.on_failure(err), self._loop)

    def _press(self, key) -> None:
        with self._lock:
            action = self.tracker.on_press(key_name(key))
        if action:
            self._emit(action)

    def _release(self, key) -> None:
        with self._lock:
            action = self.tracker.on_release(key_name(key))
        if action:
            self._emit(action)

    def learn(self) -> None:
        with self._lock:
            self.tracker.learned = None
            self.tracker.learn_waiting = True

    def stop(self) -> None:
        self.running = False
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def diagnostics(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "error": self.error,
            "ptt_key": "+".join(sorted(self.tracker.ptt.modifiers) + [self.tracker.ptt.key]),
            "mode": self.tracker.mode,
            "held": self.tracker.down_since is not None,
            "events": list(self.tracker.log),
            "learn_waiting": self.tracker.learn_waiting,
            "learned": self.tracker.learned,
        }
