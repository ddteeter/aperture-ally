"""Speech output adapters and the single-stream AudioController.

``SaySpeech`` uses the macOS built-in ``say`` utility (text via stdin, optional voice/rate/output
device) and cancels by terminating the process. It records when the process *started*; actual
audible onset through Bluetooth headphones is later and must be measured manually.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..runtime import Guard

log = logging.getLogger(__name__)


class SpeechBackend(Protocol):
    name: str

    async def speak(self, text: str, on_started: Callable[[], Awaitable[None]]) -> None:
        """Speak ``text``; raise CancelledError when cancelled. Call ``on_started`` once audio launches."""
        ...


class SaySpeech:
    name = "say"

    def __init__(self, voice: str | None = None, rate_wpm: int | None = None, audio_device: str | None = None):
        self.exe = shutil.which("say")
        self.voice, self.rate, self.device = voice, rate_wpm, audio_device

    @property
    def available(self) -> bool:
        return self.exe is not None

    def args(self) -> list[str]:
        a = [self.exe or "say"]
        if self.voice:
            a += ["-v", self.voice]
        if self.rate:
            a += ["-r", str(self.rate)]
        if self.device:
            a += ["-a", self.device]
        return a

    async def speak(self, text: str, on_started: Callable[[], Awaitable[None]]) -> None:
        if not self.exe:
            raise RuntimeError("`say` not available (macOS only)")
        proc = await asyncio.create_subprocess_exec(*self.args(), stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.PIPE)
        await on_started()
        try:
            _, err = await proc.communicate(text.encode())
            if proc.returncode not in (0, None):
                raise RuntimeError(f"say exited {proc.returncode}: {err.decode(errors='ignore')[:200]}")
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 0.5)
                except TimeoutError:
                    proc.kill()
            raise


class MockSpeech:
    """Simulated speech: 'plays' for words / words_per_s seconds; records what was said."""

    name = "mock"

    def __init__(self, words_per_s: float = 40.0):
        self.words_per_s = words_per_s
        self.spoken: list[str] = []
        self.cancelled: list[str] = []

    async def speak(self, text: str, on_started: Callable[[], Awaitable[None]]) -> None:
        await on_started()
        try:
            await asyncio.sleep(max(0.02, len(text.split()) / self.words_per_s))
        except asyncio.CancelledError:
            self.cancelled.append(text)
            raise
        self.spoken.append(text)


class NullSpeech:
    name = "none"

    async def speak(self, text: str, on_started: Callable[[], Awaitable[None]]) -> None:
        await on_started()


def play_cue(path: str) -> None:
    """Fire-and-forget system sound (macOS ``afplay``)."""
    exe = shutil.which("afplay")
    if exe:
        import subprocess

        subprocess.Popen([exe, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@dataclass
class Utterance:
    text: str
    guard: Guard
    meta: dict[str, Any] = field(default_factory=dict)
    task: asyncio.Task | None = None
    started_mono: float | None = None


class AudioController:
    """Exactly one audio output stream. Newest valid speech wins; stale speech is never started.

    ``speak`` returns 'spoken' | 'suppressed' | 'cancelled' | 'error'.
    """

    def __init__(self, backend: SpeechBackend, on_state: Callable[[str, dict], None],
                 on_mark: Callable[[str, dict], Awaitable[None]] | None = None):
        self.backend = backend
        self.on_state = on_state
        self.on_mark = on_mark
        self.current: Utterance | None = None
        self.last_spoken: Utterance | None = None
        self._lock = asyncio.Lock()
        self.stop_latencies_ms: list[float] = []

    @property
    def speaking(self) -> bool:
        return self.current is not None

    async def speak(self, text: str, guard: Guard, meta: dict[str, Any] | None = None) -> str:
        meta = meta or {}
        if not guard():
            return "suppressed"
        if self.on_mark:
            await self.on_mark("speech_requested", meta)
        # Preempt whatever is playing: one output stream.
        await self.stop("preempted")
        async with self._lock:
            if not guard():  # re-check immediately before playback
                return "suppressed"
            utt = Utterance(text, guard, meta)
            self.current = utt

            async def started() -> None:
                utt.started_mono = time.monotonic()
                self.on_state("speaking", {"text": text, **meta})
                if self.on_mark:
                    await self.on_mark("speech_process_started", meta)

            utt.task = asyncio.create_task(self.backend.speak(text, started))
        try:
            await utt.task
            status = "spoken"
            self.last_spoken = utt
            if self.on_mark:
                await self.on_mark("speech_completed", meta)
        except asyncio.CancelledError:
            status = "cancelled"
            if asyncio.current_task() and asyncio.current_task().cancelling():  # type: ignore[union-attr]
                raise
        except Exception as exc:
            log.warning("speech failed: %s", exc)
            status = "error"
        finally:
            if self.current is utt:
                self.current = None
                self.on_state("idle", {"reason": "speech_done"})
        return status

    async def stop(self, reason: str = "stopped") -> bool:
        utt = self.current
        if utt is None or utt.task is None or utt.task.done():
            return False
        t0 = time.monotonic()
        utt.task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(utt.task), 1.0)
        except (asyncio.CancelledError, TimeoutError, Exception):
            pass
        self.stop_latencies_ms.append((time.monotonic() - t0) * 1000)
        if self.current is utt:
            self.current = None
        self.on_state("idle", {"reason": reason})
        return True

    async def invalidate(self) -> None:
        """Stop current speech if its context guard no longer holds (e.g. new capture/shot switch)."""
        if self.current and not self.current.guard():
            await self.stop("obsolete")
