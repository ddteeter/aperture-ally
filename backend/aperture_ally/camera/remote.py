"""The 8BitDo Micro's camera buttons (docs/plans/remote-button-map.md) and what you hear when you press them.

D-pad ↑/↓ aperture wider/narrower · ←/→ exposure compensation −/+ · ZL/ZR ISO down/up (Auto at the bottom) ·
A shutter · Y apply the coach's suggestion · + read out the settings. L/R/B stay talk/pause/cancel (global_keys).

Feedback (the design's rapid-press rule): every step plays a tick at once (a different sound at the end of the
range); the value is spoken once, ``speak_delay_s`` after the last press. A new press cancels speech that
hasn't started, so values never queue up or arrive late. Holding a direction repeats after ``repeat_delay_s``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .service import CameraService, NotConnected

log = logging.getLogger(__name__)

STEP_BUTTONS: dict[str, tuple[str, int]] = {
    "up": ("aperture", -1),  # wider = smaller f-number
    "down": ("aperture", 1),
    "left": ("exposurecompensation", -1),
    "right": ("exposurecompensation", 1),
    "zl": ("iso", -1),
    "zr": ("iso", 1),
}
ACTION_BUTTONS = {"a": "shutter", "y": "apply", "plus": "readout"}
CAMERA_BUTTONS = set(STEP_BUTTONS) | set(ACTION_BUTTONS)

FIRST_PHOTO_NOTE = "First photo on this connection: reading the camera card, about ten seconds."


class CameraFeedback:
    def __init__(self, speak: Callable[[str], Awaitable[Any]], cue: Callable[[str], Awaitable[Any]],
                 speak_delay_s: float = 0.3):
        self._speak, self._cue = speak, cue
        self.delay = speak_delay_s
        self._pending: asyncio.Task | None = None

    def _cancel_pending(self) -> None:
        if self._pending and not self._pending.done():
            self._pending.cancel()
        self._pending = None

    async def stepped(self, result: dict[str, Any]) -> None:
        """A tick now (or the end sound); the value spoken once the presses stop."""
        self._cancel_pending()
        await self._cue("camera_end" if result.get("end") else "camera_tick")

        async def later() -> None:
            await asyncio.sleep(self.delay)
            await self._speak(result["spoken"])

        self._pending = asyncio.create_task(later())

    async def say(self, text: str) -> None:
        self._cancel_pending()
        self._pending = asyncio.create_task(self._speak(text))


class RemoteCamera:
    NO_CAMERA_EVERY_S = 3.0

    def __init__(self, camera: CameraService, feedback: CameraFeedback,
                 apply: Callable[[], Awaitable[str]] | None = None, *,
                 repeat_delay_s: float = 0.4, repeat_hz: float = 6.0):
        self.camera, self.feedback, self.apply_fn = camera, feedback, apply
        self.repeat_delay_s, self.repeat_every_s = repeat_delay_s, 1 / repeat_hz
        self._repeats: dict[str, asyncio.Task] = {}
        # Buttons down right now. A quick press can be released while its first step is still talking to the
        # camera (50–150 ms), so repeating is decided by this, not by whether a release has been seen yet.
        self._held: set[str] = set()
        self._no_camera_said = 0.0
        self.log: list[tuple[str, str]] = []

    async def press(self, name: str) -> bool:
        """Handle a camera button; False if `name` isn't one (so other handlers can have it)."""
        if name not in CAMERA_BUTTONS:
            return False
        self.log.append(("press", name))
        self._held.add(name)
        if self.camera.state != "connected":
            await self._no_camera()
            return True
        try:
            if name in STEP_BUTTONS:
                await self._step(name)
                self._start_repeat(name)
            else:
                await getattr(self, f"_{ACTION_BUTTONS[name]}")()
        except NotConnected:
            await self._no_camera()
        except Exception as exc:  # keep the remote alive whatever the camera says
            log.warning("camera button %s failed: %s", name, exc)
            await self.feedback.say("That didn't work on the camera.")
        return True

    async def release(self, name: str) -> None:
        self._held.discard(name)
        t = self._repeats.pop(name, None)
        if t:
            t.cancel()

    async def _step(self, name: str) -> dict[str, Any]:
        setting, direction = STEP_BUTTONS[name]
        r = await self.camera.step(setting, direction, source="remote")
        await self.feedback.stepped(r)
        return r

    def _start_repeat(self, name: str) -> None:
        if name not in self._held:
            return  # already released while the first step ran
        async def run() -> None:
            await asyncio.sleep(self.repeat_delay_s)
            while name in self._held:
                r = await self._step(name)
                if r.get("end"):
                    return  # at the end of the range: stop repeating (one end sound, not a stream of them)
                await asyncio.sleep(self.repeat_every_s)

        old = self._repeats.pop(name, None)
        if old:
            old.cancel()
        self._repeats[name] = asyncio.create_task(run())

    async def _shutter(self) -> None:
        r = await self.camera.trigger(source="remote")
        if r.get("first_photo"):
            await self.feedback.say(FIRST_PHOTO_NOTE)

    async def _apply(self) -> None:
        text = await self.apply_fn() if self.apply_fn else "Nothing to apply."
        await self.feedback.say(text)

    async def _readout(self) -> None:
        from . import settings as S

        self.camera._emit("camera.readout")  # the live-view screen shows the framing note again
        v = self.camera.values
        parts = [S.spoken(k, v[k]) for k in S.SETTINGS if v.get(k)]
        await self.feedback.say(", ".join(parts) or "No settings read yet.")

    async def _no_camera(self) -> None:
        now = time.monotonic()
        if now - self._no_camera_said < self.NO_CAMERA_EVERY_S:
            await self.feedback._cue("camera_end")
            return
        self._no_camera_said = now
        state = self.camera.state
        text = {"asleep": "Camera asleep. Half-press the shutter to wake it.",
                "busy_elsewhere": "OM Capture has the camera.",
                "released": "The camera is released to OM Capture.",
                "off": "Camera control is off."}.get(state, "No camera connected.")
        await self.feedback.say(text)
