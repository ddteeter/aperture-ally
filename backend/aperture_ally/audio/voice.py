"""Push-to-talk state machine and follow-up conversation.

States (published as ``voice.state.changed``): idle, listening, transcribing, preparing_response,
speaking, cancelled, error.

* Key down: interrupt speech, snapshot context (session/shot/capture), start recording, optional cue.
* Key down while already listening (auto-repeat) is ignored.
* Key up: stop recording; empty/silent clips make no API call; otherwise transcribe → answer → speak.
* Toggle mode for remotes that only send pulses. Escape/cancel stops recording or speech.
* A lost key-up cannot record forever: ``ptt_max_seconds`` fails closed (discard by default).
* A new press while a previous answer is being prepared supersedes it (voice epoch).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from ..config import Settings
from ..domain.models import AudioState, Capture, Session, VoiceTurn, utcnow
from ..events import EventBus
from ..runtime import ContextTracker
from .recording import Recorder, Transcriber
from .speech import AudioController, play_cue

log = logging.getLogger(__name__)

_ACCEPT_RX = re.compile(
    r"^\s*(please\s+)?(accept|mark|save)\s+(this|that)\s+(photo|shot|image|one|picture)\s+(as\s+)?(the\s+|a\s+)?keeper\W*$",
    re.IGNORECASE)
_REPEAT_RX = re.compile(r"^\s*(please\s+)?(repeat( that)?|say (that|it) again|what did you say)\W*$", re.IGNORECASE)
_NEXT_RX = re.compile(r"^\s*(go to\s+)?(the\s+)?next shot\W*$", re.IGNORECASE)


_PAUSE_RX = re.compile(r"^\s*(please\s+)?((pause|stop|mute)\s+(the\s+)?(coaching|coach|advice|tips)|(be\s+)?quiet(\s+please)?)\W*$",
                       re.IGNORECASE)
_RESUME_RX = re.compile(r"^\s*(please\s+)?(resume|start|unmute|restart|continue)\s+(the\s+)?(coaching|coach|advice|tips)\W*$",
                        re.IGNORECASE)
_HELPFUL_RX = re.compile(r"^\s*((that|it|this)\s+(really\s+)?(helped|worked|was helpful|made it better)|helpful|good (tip|advice))\W*$",
                         re.IGNORECASE)
_NEUTRAL_RX = re.compile(r"^\s*((that|it|this)\s+(didn'?t|did not)\s+(help|work|change anything|make a difference)|"
                         r"no (difference|change)|not helpful)\W*$", re.IGNORECASE)
_HARMFUL_RX = re.compile(r"^\s*((that|it|this)\s+made it worse|(that|it|this)\s+was (wrong|bad advice)|(bad|wrong) (tip|advice))\W*$",
                         re.IGNORECASE)
_LESSON_RX = re.compile(r"^\s*(?:(?:the\s+)?lesson(?:\s+(?:is|was))?|note)\s*[:,\-]?\s+(?P<text>.{3,})$", re.IGNORECASE)
_CHANGE_RX = re.compile(
    r"^\s*i\s+(?:just\s+)?(moved|changed|rotated|raised|lowered|turned|switched|set|added|removed|opened|closed|"
    r"stopped|swapped|used|put|shifted|tilted|angled|brought|pulled|pushed|refocused|focused|reframed|zoomed|dimmed|"
    r"brightened|softened|diffused)\b", re.IGNORECASE)


def parse_command(transcript: str) -> tuple[str, str | None]:
    """Map a transcript to (intent, payload). Anything unrecognised is a question for the coach."""
    t = transcript.strip()
    if _ACCEPT_RX.match(t):
        return "accept_keeper", None
    if _REPEAT_RX.match(t):
        return "repeat", None
    if _NEXT_RX.match(t):
        return "next_shot", None
    if _PAUSE_RX.match(t):
        return "pause_coaching", None
    if _RESUME_RX.match(t):
        return "resume_coaching", None
    if _HARMFUL_RX.match(t):
        return "rate", "harmful"
    if _NEUTRAL_RX.match(t):
        return "rate", "neutral"
    if _HELPFUL_RX.match(t):
        return "rate", "helpful"
    m = _LESSON_RX.match(t)
    if m:
        return "lesson", m.group("text").strip()
    if _CHANGE_RX.match(t) and "?" not in t:
        return "change_note", t.rstrip(".")
    return "question", None


def classify(transcript: str) -> str:
    return parse_command(transcript)[0]


class VoiceController:
    def __init__(self, *, store, bus: EventBus, settings: Settings, tracker: ContextTracker,
                 audio: AudioController, recorder: Recorder, transcriber: Transcriber, app):
        self.store = store
        self.bus = bus
        self.settings = settings
        self.tracker = tracker
        self.audio = audio
        self.recorder = recorder
        self.transcriber = transcriber
        self.app = app  # for session actions (keeper, next shot, coaching)
        self.state = AudioState.idle
        self.turn: VoiceTurn | None = None
        self._t0 = 0.0
        self._timeout_task: asyncio.Task | None = None
        self._processing: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.repeats_ignored = 0

    def set_state(self, state: AudioState | str, **info: Any) -> None:
        self.state = AudioState(state)
        self.bus.publish("voice.state.changed", session_id=self.turn.session_id if self.turn else None,
                         state=self.state.value, turn_id=self.turn.id if self.turn else None, **info)

    def on_audio_state(self, state: str, info: dict) -> None:
        """Called by AudioController as speech starts/stops."""
        if state == "speaking":
            self.bus.publish("coach.speech.started", session_id=info.get("session_id"),
                             capture_id=info.get("capture_id"), text=info.get("text"), kind=info.get("kind"))
            if self.state != AudioState.listening:
                self.state = AudioState.speaking
                self.bus.publish("voice.state.changed", session_id=info.get("session_id"), state="speaking")
        else:
            self.bus.publish("coach.speech.stopped", reason=info.get("reason"))
            if self.state == AudioState.speaking:
                self.state = AudioState.idle
                self.bus.publish("voice.state.changed", state="idle")

    # --- PTT -----------------------------------------------------------------------------
    async def press(self, session_id: str | None, *, capture_id: str | None = None, source: str = "ui") -> dict:
        async with self._lock:
            if self.state == AudioState.listening:
                self.repeats_ignored += 1
                return {"ignored": "already listening"}
            if session_id is None:
                return {"error": "no active session"}
            await self.audio.stop("ptt")  # interrupt promptly
            if self._processing and not self._processing.done():
                self._processing.cancel()
            ctx = self.tracker.get(session_id)
            ctx.voice_epoch += 1
            if capture_id is None and ctx.active_shot_id:
                capture_id = ctx.latest_capture.get(ctx.active_shot_id)
            cap = await self.store.get(Capture, capture_id) if capture_id else None
            self.turn = VoiceTurn(session_id=session_id, shot_id=cap.shot_id if cap else ctx.active_shot_id,
                                  capture_id=cap.id if cap else None, voice_epoch=ctx.voice_epoch)
            await self.store.put(self.turn)
            try:
                if self.settings.ready_cue and self.settings.speech_provider == "say":
                    play_cue(self.settings.ready_cue_sound)
                self.recorder.start()
            except Exception as exc:
                await self._finish_turn("error", error=f"microphone: {exc}")
                self.set_state(AudioState.error, error=str(exc))
                self.state = AudioState.idle
                return {"error": str(exc)}
            self._t0 = time.monotonic()
            self._timeout_task = asyncio.create_task(self._timeout(self.turn.id))
            self.set_state(AudioState.listening, source=source, capture_id=self.turn.capture_id)
            return {"turn_id": self.turn.id, "capture_id": self.turn.capture_id}

    async def release(self, *, source: str = "ui") -> dict:
        async with self._lock:
            if self.state != AudioState.listening or not self.turn:
                return {"ignored": "not listening"}
            self._cancel_timeout()
            clip = self.recorder.stop()
            turn = self.turn
            turn.duration_s = round(time.monotonic() - self._t0, 3)
            if clip.is_empty(self.settings.min_utterance_s):
                await self._finish_turn("empty")
                self.set_state(AudioState.idle, reason="empty clip; nothing sent")
                return {"turn_id": turn.id, "status": "empty"}
            self.set_state(AudioState.transcribing, source=source)
            self._processing = asyncio.create_task(self._process(turn, clip))
            return {"turn_id": turn.id, "status": "transcribing"}

    async def toggle(self, session_id: str | None, *, capture_id: str | None = None, source: str = "ui") -> dict:
        if self.state == AudioState.listening:
            return await self.release(source=source)
        return await self.press(session_id, capture_id=capture_id, source=source)

    async def cancel(self, reason: str = "user") -> dict:
        async with self._lock:
            self._cancel_timeout()
            did = []
            if self.state == AudioState.listening:
                self.recorder.abort()
                await self._finish_turn("cancelled", error=reason)
                did.append("recording")
            if self._processing and not self._processing.done():
                self._processing.cancel()
                did.append("processing")
            if await self.audio.stop("cancel"):
                did.append("speech")
            if self.turn:
                self.tracker.get(self.turn.session_id).voice_epoch += 1
            self.set_state(AudioState.cancelled, cancelled=did, reason=reason)
            self.state = AudioState.idle
            self.bus.publish("voice.state.changed", state="idle")
            return {"cancelled": did}

    async def listener_failed(self, error: str) -> None:
        """Global key listener/device died: never leave the mic open."""
        if self.state == AudioState.listening:
            await self.cancel(f"listener failure: {error}")

    def _cancel_timeout(self) -> None:
        if self._timeout_task and not self._timeout_task.done():
            self._timeout_task.cancel()
        self._timeout_task = None

    async def _timeout(self, turn_id: str) -> None:
        await asyncio.sleep(self.settings.ptt_max_seconds)
        if self.state == AudioState.listening and self.turn and self.turn.id == turn_id:
            self.bus.publish("voice.timeout", turn_id=turn_id, action=self.settings.ptt_timeout_action)
            if self.settings.ptt_timeout_action == "submit":
                self._timeout_task = None
                await self.release(source="timeout")
            else:
                async with self._lock:
                    self.recorder.abort()
                    await self._finish_turn("timed_out", error="max recording duration reached (key-up lost?)")
                    self.set_state(AudioState.idle, reason="timeout")

    async def _finish_turn(self, status: str, **fields: Any) -> None:
        if not self.turn:
            return
        self.turn.status = status  # type: ignore[assignment]
        for k, v in fields.items():
            setattr(self.turn, k, v)
        await self.store.put(self.turn)

    # --- answering -----------------------------------------------------------------------
    async def _process(self, turn: VoiceTurn, clip) -> None:
        guard = self.tracker.voice_guard(turn.session_id)
        t0 = time.monotonic()
        turn.meta.update({"clip_duration_s": round(clip.duration_s, 3), "clip_rms": round(clip.rms, 1),
                          "clip_bytes": len(clip.wav), "transcriber": self.transcriber.name,
                          "transcription_model": getattr(self.transcriber, "model", None),
                          "recorder": self.recorder.name})
        try:
            text, _call = await self.app.telemetry_calls.call(
                lambda: self.transcriber.transcribe(clip), purpose="transcribe", attempt=0,
                provider=self.transcriber, collect=turn.model_call_ids,
                request_extra={"clip_duration_s": round(clip.duration_s, 3), "clip_bytes": len(clip.wav)},
                session_id=turn.session_id, capture_id=turn.capture_id, voice_turn_id=turn.id)
            turn.timings["transcribe_ms"] = (time.monotonic() - t0) * 1000
            turn.transcript = text
            if self.settings.keep_voice_audio:
                folder = self.settings.sessions_dir / turn.session_id / "voice"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{turn.id}.wav").write_bytes(clip.wav)
                turn.audio_path = str(folder / f"{turn.id}.wav")
            if not text.strip():
                turn.status = "empty"
                await self.store.put(turn)
                self.set_state(AudioState.idle, reason="empty transcript")
                return
            turn.intent, turn.meta["command_payload"] = parse_command(text)
            turn.status = "answering"
            await self.store.put(turn)
            self.bus.publish("voice.transcript", session_id=turn.session_id, turn_id=turn.id, transcript=text,
                             intent=turn.intent)
            if guard():
                self.set_state(AudioState.preparing_response, intent=turn.intent)
            spoken, answer = await self._respond(turn)
            turn.answer = answer
            turn.timings["answer_ms"] = (time.monotonic() - t0) * 1000
            turn.status = "answered"
            await self.store.put(turn)
            self.bus.publish("voice.answer", session_id=turn.session_id, turn_id=turn.id, answer=answer,
                             capture_id=turn.capture_id)
            if spoken:
                t_sp = time.monotonic()
                turn.timings["release_to_speech_request_ms"] = (t_sp - t0) * 1000
                status = await self.audio.speak(spoken, guard, {"session_id": turn.session_id, "capture_id": turn.capture_id,
                                                                "voice_turn_id": turn.id, "kind": "answer"})
                turn.timings["speech_call_ms"] = (time.monotonic() - t_sp) * 1000
                turn.meta["speech_status"] = status
                turn.status = "spoken" if status == "spoken" else "suppressed" if status == "suppressed" else "answered"
                await self.store.put(turn)
        except asyncio.CancelledError:
            turn.status = "cancelled"
            await self.store.put(turn)
            raise
        except Exception as exc:
            log.exception("voice turn failed")
            from ..coaching.budget import BudgetExceeded
            from ..coaching.providers.base import ProviderUnavailable

            offline = isinstance(exc, ProviderUnavailable | TimeoutError)
            if isinstance(exc, BudgetExceeded):
                turn.status, turn.error = "error", f"Budget reached: {exc}"
                await self.store.put(turn)
                self.set_state(AudioState.error, error=turn.error)
                await self.audio.speak("The coaching budget is used up, so I can't answer. Raise it in the app.",
                                       guard, {"session_id": turn.session_id, "voice_turn_id": turn.id, "kind": "notice"})
                return
            turn.status = "error"
            turn.error = ("AI unavailable: " if offline else "") + str(exc)
            await self.store.put(turn)
            self.set_state(AudioState.error, error=turn.error, ai_unavailable=offline)
            # Drew is at the camera, not the screen: say briefly (local speech) that there's no answer.
            msg = ("The coach is offline, so I can't answer right now." if offline
                   else "Sorry, that question failed. Check the screen.")
            await self.audio.speak(msg, guard, {"session_id": turn.session_id, "voice_turn_id": turn.id,
                                                "kind": "notice"})
        finally:
            if self.state in (AudioState.transcribing, AudioState.preparing_response, AudioState.error):
                self.state = AudioState.idle
                self.bus.publish("voice.state.changed", state="idle")

    async def _respond(self, turn: VoiceTurn) -> tuple[str | None, str]:
        session = await self.store.get(Session, turn.session_id)
        assert session is not None
        cap = await self.store.get(Capture, turn.capture_id) if turn.capture_id else None
        if turn.intent == "repeat":
            last = self.audio.last_spoken
            if last is None:
                return "Nothing to repeat yet.", "Nothing to repeat yet."
            return last.text, last.text
        if turn.intent == "next_shot":
            shot = await self.app.advance_shot(session.id)
            msg = f"Next shot: {shot.title}. {shot.purpose}" if shot else "Every shot has an accepted keeper."
            return msg, msg
        if turn.intent == "pause_coaching":
            await self.app.set_coaching_paused(session.id, True, reason="paused by voice")
            msg = "Coaching paused. Photos are still saved."
            return msg, msg
        if turn.intent == "resume_coaching":
            s2 = await self.app.set_coaching_paused(session.id, False)
            msg = "Coaching resumed."
            if s2.paused_reason and s2.paused_reason.startswith("budget"):
                msg = "The coaching budget is still used up. Raise it in the app to continue."
            return msg, msg
        if turn.intent in ("rate", "lesson"):
            exp = await self.app.experiment_for_feedback(session.id, cap)
            if exp is None:
                return "There's no advice to rate yet.", "No experiment found to attach this to."
            payload = turn.meta.get("command_payload") or ""
            if turn.intent == "rate":
                exp = await self.app.update_experiment(exp.id, {"user_rating": payload})
                short = " ".join(exp.suggested_adjustment.split()[:8])
                return f"Marked {payload}: {short}.", f"Rated '{exp.suggested_adjustment}' as {payload}."
            lesson = f"{exp.lesson} | {payload}" if exp.lesson else payload
            await self.app.update_experiment(exp.id, {"lesson": lesson})
            return "Lesson saved.", f"Lesson saved on '{exp.suggested_adjustment}': {payload}"
        if turn.intent == "change_note":
            await self.app.set_change_note(session.id, turn.meta.get("command_payload") or turn.transcript)
            return "Noted for the next photo.", f"Change note for the next photo: {turn.transcript}"
        if turn.intent == "accept_keeper":
            if cap is None or not cap.shot_id:
                return "There's no current photo to accept.", "No current photo; nothing accepted."
            from ..domain.models import ShotRequirement

            shot = await self.store.get(ShotRequirement, cap.shot_id)
            await self.app.keepers.accept(cap.shot_id, cap.id, source="voice")
            msg = f"Accepted photo {cap.seq} as the keeper for {shot.title if shot else 'this shot'}."
            return msg, msg
        # Question: use the saved assessment for this capture; wait briefly if analysis is in flight.
        if cap:
            t_wait = time.monotonic()
            await self.app.coaching.wait_inflight(cap.id, timeout=self.settings.model_timeout_s)
            turn.timings["waited_for_assessment_ms"] = (time.monotonic() - t_wait) * 1000
        is_older = bool(cap and not self.tracker.is_latest(session.id, cap.shot_id, cap.id))
        ans, meta = await self.app.coaching.answer_question(session, cap, turn.transcript or "", is_older,
                                                            voice_turn_id=turn.id)
        turn.timings["model_ms"] = meta.get("latency_ms", 0)
        turn.model_call_ids.extend(meta.pop("model_call_ids", []))
        turn.meta.update({"answer": {**meta, "is_older_photo": is_older}})
        spoken = ans.spoken_text
        if is_older and cap and "earlier" not in spoken.lower():
            spoken = f"About earlier photo {cap.seq}: {spoken}"
        return spoken, ans.answer

    def snapshot(self) -> dict:
        return {"state": self.state.value, "turn": self.turn.model_dump() if self.turn else None,
                "repeats_ignored": self.repeats_ignored, "at": utcnow()}
