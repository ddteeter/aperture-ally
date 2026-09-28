"""In-memory "current context" per session, used to suppress stale speech.

Every analysis/speech job carries a guard built from a snapshot of this context. The guard is
re-evaluated immediately before audio playback (and whenever context changes), so advice for a
superseded photo, a previous shot, or a pre-question context is never spoken.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

Guard = Callable[[], bool]


@dataclass
class SessionContext:
    session_id: str
    active_shot_id: str | None = None
    setup_revision_id: str | None = None
    shot_changed_mono: float = 0.0
    previous_shot_id: str | None = None  # shot that was active before the latest switch
    generation: int = 0
    voice_epoch: int = 0
    pending_change: str | None = None  # 'what I changed' note for the next capture of the active shot
    user_request_epoch: int = 0
    latest_capture: dict[str, str] = field(default_factory=dict)  # shot_id -> newest ready capture id
    latest_seq: dict[str, int] = field(default_factory=dict)

    def bump(self) -> int:
        self.generation += 1
        return self.generation


class ContextTracker:
    def __init__(self) -> None:
        self._ctx: dict[str, SessionContext] = {}

    def get(self, session_id: str) -> SessionContext:
        if session_id not in self._ctx:
            self._ctx[session_id] = SessionContext(session_id)
        return self._ctx[session_id]

    def set_active_shot(self, session_id: str, shot_id: str | None, *, initial: bool = False) -> SessionContext:
        ctx = self.get(session_id)
        if ctx.active_shot_id != shot_id:
            ctx.previous_shot_id = None if initial else ctx.active_shot_id
            ctx.active_shot_id = shot_id
            ctx.shot_changed_mono = 0.0 if initial else time.monotonic()
            ctx.bump()
        return ctx

    def capture_ready(self, session_id: str, shot_id: str | None, capture_id: str, seq: int,
                      later_bracket_frame: bool = False) -> bool:
        """Record a new ready capture; returns True if it is now the newest for its shot.

        Later frames of an in-camera bracket (shot 2..N) don't count: the base frame stands for the set, so its
        advice isn't suppressed as stale while the rest of the set arrives.
        """
        ctx = self.get(session_id)
        if shot_id is None or later_bracket_frame:
            return False
        if seq >= ctx.latest_seq.get(shot_id, -1):
            ctx.latest_capture[shot_id] = capture_id
            ctx.latest_seq[shot_id] = seq
            ctx.bump()
            return True
        return False

    # --- guards --------------------------------------------------------------------------
    @staticmethod
    def later_bracket_frame(exif: dict | None) -> bool:
        b = (exif or {}).get("bracket")
        return bool(b and b.get("shot", 1) > 1)

    def auto_guard(self, session_id: str, shot_id: str | None, capture_id: str) -> Guard:
        ctx = self.get(session_id)
        epoch = ctx.voice_epoch
        return lambda: (
            ctx.active_shot_id == shot_id
            and ctx.latest_capture.get(shot_id or "") == capture_id
            and ctx.voice_epoch == epoch
        )

    def voice_guard(self, session_id: str) -> Guard:
        ctx = self.get(session_id)
        epoch = ctx.voice_epoch
        return lambda: ctx.voice_epoch == epoch

    def user_guard(self, session_id: str) -> Guard:
        ctx = self.get(session_id)
        ctx.user_request_epoch += 1
        epoch, vepoch = ctx.user_request_epoch, ctx.voice_epoch
        return lambda: ctx.user_request_epoch == epoch and ctx.voice_epoch == vepoch

    def is_latest(self, session_id: str, shot_id: str | None, capture_id: str) -> bool:
        return self.get(session_id).latest_capture.get(shot_id or "") == capture_id
