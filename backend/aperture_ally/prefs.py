"""Personal audio preferences changed from the UI while the app runs: speech speed, received sound, cue volume.

Stored in ``<data dir>/prefs.json`` (per person, not per session); ``.env`` values are the defaults. The app
applies them live to the ``say`` speech backend and the cue player, so no restart is needed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from .config import Settings

log = logging.getLogger(__name__)

SOUNDS_DIR = Path("/System/Library/Sounds")
SPEECH_RATE_MIN, SPEECH_RATE_MAX = 120, 400
CUE_VOLUME_MIN, CUE_VOLUME_MAX = 0.25, 4.0


class AudioPrefs(BaseModel):
    speech_rate_wpm: int = Field(ge=SPEECH_RATE_MIN, le=SPEECH_RATE_MAX)
    received_sound: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9 _-]+$")  # a macOS system sound
    cue_volume: float = Field(ge=CUE_VOLUME_MIN, le=CUE_VOLUME_MAX)


def system_sounds() -> list[str]:
    return sorted(p.stem for p in SOUNDS_DIR.glob("*.aiff")) if SOUNDS_DIR.is_dir() else []


def sound_path(name: str) -> str:
    return str(SOUNDS_DIR / f"{name}.aiff")


def defaults(settings: Settings) -> AudioPrefs:
    return AudioPrefs(speech_rate_wpm=settings.say_rate_wpm or 190,
                      received_sound=Path(settings.received_cue_sound).stem,
                      cue_volume=settings.cue_volume)


class PrefsStore:
    def __init__(self, path: Path, settings: Settings):
        self.path = path
        self.defaults = defaults(settings)
        self.current = self.defaults
        try:
            saved = json.loads(path.read_text())
            self.current = AudioPrefs(**{**self.defaults.model_dump(), **saved})
        except FileNotFoundError:
            pass
        except (ValueError, ValidationError) as exc:
            log.warning("ignoring invalid %s: %s", path, exc)

    def update(self, patch: dict[str, Any]) -> AudioPrefs:
        """Validate and save; raises ValueError for an out-of-range value or an unknown sound."""
        unknown = set(patch) - set(AudioPrefs.model_fields)
        if unknown:
            raise ValueError(f"unknown preference(s): {sorted(unknown)}")
        try:
            new = AudioPrefs(**{**self.current.model_dump(), **patch})
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        sounds = system_sounds()
        if sounds and new.received_sound not in sounds:
            raise ValueError(f"unknown sound {new.received_sound!r}; choose one of {sounds}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(new.model_dump(), indent=2))
        tmp.replace(self.path)
        self.current = new
        return new
