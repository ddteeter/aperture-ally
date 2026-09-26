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
        return (getattr(res, "text", None) or str(res)).strip()


class MockTranscriber:
    name = "mock"

    def __init__(self, scripted: list[str] | None = None, default: str = "Why did you suggest that?"):
        self.queue: deque[str] = deque(scripted or [])
        self.default = default

    async def transcribe(self, clip: Clip) -> str:
        return self.queue.popleft() if self.queue else self.default
