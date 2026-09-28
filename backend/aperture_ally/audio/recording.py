"""Microphone capture and transcription adapters.

The Bluetooth remote only sends key events; audio comes from the selected Mac/headset microphone.
Audio is kept in memory and discarded after transcription unless ``keep_voice_audio`` is enabled.
"""

from __future__ import annotations

import io
import time
import wave
from collections import deque
from dataclasses import dataclass
from typing import Protocol

import numpy as np

SAMPLE_RATE = 16000


@dataclass
class Clip:
    wav: bytes
    duration_s: float
    rms: float

    def is_empty(self, min_s: float, min_rms: float = 80.0) -> bool:
        return self.duration_s < min_s or self.rms < min_rms


def to_wav(samples: np.ndarray, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype(np.int16).tobytes())
    return buf.getvalue()


class Recorder(Protocol):
    name: str

    def start(self) -> None: ...

    def stop(self) -> Clip: ...

    def abort(self) -> None: ...


class SoundDeviceRecorder:
    name = "sounddevice"

    def __init__(self, device: str | int | None = None):
        import sounddevice  # noqa: F401  (fail early if PortAudio missing)

        self.device = device
        self._stream = None
        self._frames: deque[np.ndarray] = deque()
        self._t0 = 0.0

    def start(self) -> None:
        import sounddevice as sd

        self._frames.clear()

        def cb(indata, frames, t, status):
            self._frames.append(indata.copy())

        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", device=self.device,
                                      callback=cb)
        self._stream.start()
        self._t0 = time.monotonic()

    def _close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def stop(self) -> Clip:
        self._close()
        data = np.concatenate(list(self._frames)).reshape(-1) if self._frames else np.zeros(0, np.int16)
        self._frames.clear()
        rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2))) if data.size else 0.0
        return Clip(to_wav(data), data.size / SAMPLE_RATE, rms)

    def abort(self) -> None:
        self._close()
        self._frames.clear()


class ContinuousRecorder:
    """Keeps the mic open for the whole run and slices push-to-talk clips out of it.

    Opening a Bluetooth headset's mic switches it to call mode, which took ~0.6 s on the owner's AirPods Pro,
    and speech in that window was lost. Holding the stream open removes the switch from every turn, and
    enables a pre-roll: a clip starts ``preroll_ms`` before the press. Outside a turn, audio only lives in a
    ~2 s ring buffer that is continuously overwritten: never stored, never sent. A dead stream (headphones
    in the case, battery) is reopened by ``ensure_open``; ``last_error`` says why it's down.
    """

    name = "sounddevice-open"

    def __init__(self, device: str | int | None = None, preroll_ms: int = 300, ring_s: float = 2.0,
                 stream_factory=None):
        import threading

        self.device = device
        self.preroll = int(SAMPLE_RATE * preroll_ms / 1000)
        self.ring_max = int(SAMPLE_RATE * ring_s)
        self._factory = stream_factory
        self._lock = threading.Lock()
        self._ring: deque[np.ndarray] = deque()
        self._ring_n = 0
        self._clip: list[np.ndarray] | None = None
        self._opened_at: float | None = None
        self._stream = None
        self.last_error: str | None = None
        self.reopened = 0
        self.last_stall: str | None = None        # why the stream was last reopened
        self._clock = time.monotonic
        self.last_audio_at: float | None = None   # any callback
        self.last_signal_at: float | None = None  # a callback that wasn't all zeros (a live mic never is)
        self.level = 0.0                          # rms of the latest block

    # --- the PortAudio thread ----------------------------------------------------------------
    def _on_audio(self, indata, frames, t, status) -> None:
        a = indata.reshape(-1).copy()
        now = self._clock()
        self.last_audio_at = now
        if a.size and np.any(a):
            self.last_signal_at = now
        self.level = float(np.sqrt(np.mean(a.astype(np.float32) ** 2))) if a.size else 0.0
        with self._lock:
            self._ring.append(a)
            self._ring_n += a.size
            while self._ring and self._ring_n - self._ring[0].size >= self.ring_max:
                self._ring_n -= self._ring.popleft().size
            if self._clip is not None:
                self._clip.append(a)

    # --- lifecycle ---------------------------------------------------------------------------
    NO_AUDIO_S = 1.5      # no callbacks: the device went away under an "active" stream
    ZERO_SIGNAL_S = 3.0   # callbacks of pure zeros: a dead or muted device

    @property
    def is_open(self) -> bool:
        s = self._stream
        return s is not None and bool(getattr(s, "active", True))

    def stalled(self) -> str | None:
        """Why an open stream isn't really delivering audio (e.g. AirPods in the case), else None."""
        if not self.is_open or self._opened_at is None:
            return None
        now = self._clock()
        last_audio = self.last_audio_at or self._opened_at
        if now - last_audio > self.NO_AUDIO_S:
            return f"no audio for {now - last_audio:.1f} s"
        last_signal = self.last_signal_at or self._opened_at
        if now - last_signal > self.ZERO_SIGNAL_S:
            return f"silent (all zeros) for {now - last_signal:.1f} s"
        return None

    def status(self) -> dict:
        now = self._clock()
        return {"open": self.is_open, "stalled": self.stalled(), "error": self.last_error, "reopened": self.reopened,
                "last_stall": self.last_stall,
                "device": self.device, "level": round(self.level, 1),
                "since_audio_s": round(now - self.last_audio_at, 2) if self.last_audio_at else None}

    def open(self) -> None:
        if self.is_open:
            return
        self._close_stream()
        factory = self._factory
        if factory is None:
            import sounddevice as sd

            factory = sd.InputStream
        try:
            self._stream = factory(samplerate=SAMPLE_RATE, channels=1, dtype="int16", device=self.device,
                                   callback=self._on_audio)
            self._stream.start()
            self._opened_at = self._clock()
            self.last_audio_at = self.last_signal_at = None
            self.last_error = None
        except Exception as exc:
            self._stream = None
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise

    def ensure_open(self) -> bool:
        """Reopen a dead or stalled stream (called periodically). True when the mic is open and live afterwards."""
        why = self.stalled()
        if why:
            self.last_stall = f"{why} (reopened)"
            self._close_stream()
        if self.is_open:
            return True
        opened_before = self._opened_at is not None
        try:
            self.open()
            if opened_before:
                self.reopened += 1
            return True
        except Exception:
            return False

    def _close_stream(self) -> None:
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

    def close(self) -> None:
        self._close_stream()
        with self._lock:
            self._ring.clear()
            self._ring_n = 0
            self._clip = None

    # --- push-to-talk ------------------------------------------------------------------------
    def start(self) -> None:
        if not self.is_open:
            self.open()  # raises with the reason if the mic is gone
        with self._lock:
            tail: list[np.ndarray] = []
            n = 0
            for a in reversed(self._ring):
                if n >= self.preroll:
                    break
                tail.append(a)
                n += a.size
            pre = np.concatenate(tail[::-1])[-self.preroll:] if tail and self.preroll else np.zeros(0, np.int16)
            self._clip = [pre]

    def stop(self) -> Clip:
        with self._lock:
            parts, self._clip = self._clip or [], None
        data = np.concatenate(parts).reshape(-1) if parts else np.zeros(0, np.int16)
        rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2))) if data.size else 0.0
        return Clip(to_wav(data), data.size / SAMPLE_RATE, rms)

    def abort(self) -> None:
        with self._lock:
            self._clip = None


class MockRecorder:
    """Simulated mic: duration = hold time; loudness configurable so tests can model silence."""

    name = "mock"

    def __init__(self, rms: float = 1000.0):
        self.rms = rms
        self._t0: float | None = None
        self.active = False

    def start(self) -> None:
        self._t0 = time.monotonic()
        self.active = True

    def stop(self) -> Clip:
        dur = time.monotonic() - (self._t0 or time.monotonic())
        self.active = False
        n = int(min(dur, 1.0) * SAMPLE_RATE)
        return Clip(to_wav(np.zeros(n, np.int16)), dur, self.rms)

    def abort(self) -> None:
        self.active = False


class Transcriber(Protocol):
    name: str

    async def transcribe(self, clip: Clip) -> str: ...


class OpenAITranscriber:
    name = "openai"

    def __init__(self, api_key: str, model: str, timeout_s: float = 30.0):
        from openai import AsyncOpenAI

        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, timeout=timeout_s, max_retries=1)

    async def transcribe(self, clip: Clip) -> str:
        import openai

        from ..coaching.providers.base import ProviderUnavailable

        try:
            res = await self.client.audio.transcriptions.create(model=self.model, file=("utterance.wav", clip.wav))
        except (openai.APIConnectionError, openai.APITimeoutError, openai.AuthenticationError) as exc:
            raise ProviderUnavailable(str(exc)) from exc
        # An empty transcript must stay empty (it used to fall back to the SDK object's repr, which then went
        # to the coach as a "question"). A plain-text response format returns a str.
        text = res if isinstance(res, str) else getattr(res, "text", None)
        return (text or "").strip()


class MockTranscriber:
    name = "mock"

    def __init__(self, scripted: list[str] | None = None, default: str = "Why did you suggest that?"):
        self.queue: deque[str] = deque(scripted or [])
        self.default = default

    async def transcribe(self, clip: Clip) -> str:
        return self.queue.popleft() if self.queue else self.default
