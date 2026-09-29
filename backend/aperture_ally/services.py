"""Application container: constructs adapters/services and owns session-level operations."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .audio.recording import (
    ContinuousRecorder,
    MockRecorder,
    MockTranscriber,
    OpenAITranscriber,
    Recorder,
    SoundDeviceRecorder,
    Transcriber,
)
from .audio.speech import (
    AudioController,
    CompanionSpeech,
    CuePlayer,
    MockCuePlayer,
    MockSpeech,
    NullSpeech,
    SaySpeech,
    SpeechBackend,
)
from .audio.voice import VoiceController
from .coaching.providers.base import Provider
from .coaching.service import CoachingService, ProviderRegistry
from .config import Settings
from .coverage import KeeperService
from .domain.models import (
    Assessment,
    Capture,
    Session,
    SessionStatus,
    SetupFields,
    SetupRevision,
    ShotRequirement,
    utcnow,
)
from .events import EventBus
from .imaging.metadata import MetadataReader
from .ingest.service import IngestService
from .persistence.db import AsyncStore, Store
from .prefs import PrefsStore, sound_path
from .projects import ProjectService, template_shot_fields
from .runtime import ContextTracker
from .telemetry.recorder import (
    PROVIDER_HOSTS,
    ModelCallRecorder,
    NetworkMonitor,
    TelemetrySink,
    setup_file_logging,
    startup_snapshot,
)
from .telemetry.timing import Timer
from .templates import TEMPLATES, template_shots

log = logging.getLogger(__name__)


class NotFound(Exception):
    pass


def build_cues(settings: Settings):
    if settings.speech_provider in ("say", "companion"):
        return CuePlayer({"received": settings.received_cue_sound, "failure": settings.failure_cue_sound,
                          "camera_tick": settings.camera_tick_sound, "camera_end": settings.camera_end_sound},
                         settings.cue_volume)
    return MockCuePlayer()


def build_speech(settings: Settings) -> SpeechBackend:
    if settings.speech_provider == "say":
        return SaySpeech(settings.say_voice, settings.say_rate_wpm, settings.say_audio_device,
                         settings.say_tail_silence_ms)
    if settings.speech_provider == "companion":
        fallback = SaySpeech(settings.say_voice, settings.say_rate_wpm, settings.say_audio_device,
                             settings.say_tail_silence_ms)
        return CompanionSpeech(settings.companion_port, settings.say_rate_wpm, settings.say_voice, fallback)
    if settings.speech_provider == "mock":
        return MockSpeech()
    return NullSpeech()


def build_recorder(settings: Settings) -> Recorder:
    if settings.recorder == "sounddevice":
        if settings.mic_always_open:
            return ContinuousRecorder(settings.input_device, settings.ptt_preroll_ms)
        return SoundDeviceRecorder(settings.input_device)
    return MockRecorder()


def build_transcriber(settings: Settings) -> Transcriber:
    if settings.transcriber == "openai":
        if not settings.openai_api_key or not settings.transcription_model:
            log.warning("OpenAI transcription not configured; using mock transcriber")
            return MockTranscriber(settings.mock_transcripts)
        return OpenAITranscriber(settings.openai_api_key.get_secret_value(), settings.transcription_model)
    return MockTranscriber(settings.mock_transcripts)


class ApertureAllyApp:
    def __init__(self, settings: Settings, *, providers: dict[str, Provider] | None = None,
                 speech: SpeechBackend | None = None, recorder: Recorder | None = None,
                 transcriber: Transcriber | None = None, store: Store | None = None, cues=None):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.store_sync = store or Store(settings.db_path)
        self.store = AsyncStore(self.store_sync)
        self.bus = EventBus()
        self.telemetry = TelemetrySink(self.store)
        self.bus.sinks.append(self.telemetry)  # every app event is persisted for later analysis
        self.network = NetworkMonitor(settings, self.telemetry, self._provider_hosts)
        self.telemetry_calls = ModelCallRecorder(self.store, settings, self.network, self.telemetry)
        self.log_path = setup_file_logging(settings.data_dir) if settings.log_to_file else None
        self.tracker = ContextTracker()
        self.timer = Timer(self.store)
        self.executor = ThreadPoolExecutor(max_workers=settings.image_workers, thread_name_prefix="img")
        self.metadata = MetadataReader()
        self.providers = ProviderRegistry(settings, providers)
        self.speech = speech or build_speech(settings)
        self.voice: VoiceController  # set below (audio callbacks reference it)
        self.audio = AudioController(self.speech, on_state=lambda s, i: self.voice.on_audio_state(s, i),
                                     on_mark=self._speech_mark, on_event=self._audio_event)
        self.keepers = KeeperService(self.store, self.bus)
        self.coaching = CoachingService(store=self.store, bus=self.bus, timer=self.timer, settings=settings,
                                        tracker=self.tracker, executor=self.executor, providers=self.providers,
                                        audio=self.audio, session_root=self.session_root,
                                        recorder=self.telemetry_calls)
        self.coaching.on_budget_exceeded = self._budget_exceeded
        self.coaching.reachable = self._provider_reachable
        self.network.on_probe = lambda result: (
            self.coaching.poke_online() if any(p.get("ok") for p in result.get("probes", [])) else None)
        self.cues = cues or build_cues(settings)
        self.prefs = PrefsStore(settings.data_dir / "prefs.json", settings)
        self.projects = ProjectService(self.store, settings)
        self._mic_task: asyncio.Task | None = None
        self.apply_prefs()
        self.bus.sinks.append(self._cue_sink)
        self.ingest = IngestService(store=self.store, bus=self.bus, timer=self.timer, settings=settings,
                                    tracker=self.tracker, executor=self.executor, metadata=self.metadata,
                                    on_ready=self.coaching.on_capture_ready)
        self.voice = VoiceController(store=self.store, bus=self.bus, settings=settings, tracker=self.tracker,
                                     audio=self.audio, recorder=recorder or build_recorder(settings),
                                     transcriber=transcriber or build_transcriber(settings), app=self)
        self.keys = None
        from .camera.driver import FakeDriver, GPhotoDriver
        from .camera.service import CameraService

        fake = FakeDriver() if settings.camera == "mock" else None
        self.camera = CameraService(
            settings.camera, (lambda: fake) if fake else GPhotoDriver, self.bus.publish,
            inbox=settings.data_dir / "camera-inbox", poll_s=settings.camera_poll_s,
            destination_fn=lambda: self.ingest.watched_folder)
        from .camera.remote import CameraFeedback, RemoteCamera

        self.remote_camera = RemoteCamera(
            self.camera,
            CameraFeedback(lambda text: self.audio.speak(text, lambda: True, {"kind": "camera"}), self._camera_cue,
                           settings.camera_speak_delay_ms / 1000),
            self.apply_camera_suggestion,
            repeat_delay_s=settings.camera_repeat_delay_ms / 1000, repeat_hz=settings.camera_repeat_hz)
        self.started = False

    def _provider_hosts(self) -> list[str]:
        s, hosts = self.settings, set()
        if s.openai_api_key and (s.openai_model or s.transcriber == "openai"):
            hosts.add(PROVIDER_HOSTS["openai"])
        if s.gemini_api_key and s.gemini_model:
            hosts.add(PROVIDER_HOSTS["gemini"])
        if s.anthropic_api_key and s.claude_model:
            hosts.add(PROVIDER_HOSTS["claude"])
        return sorted(hosts)

    async def _provider_reachable(self, name: str) -> bool:
        """Is the provider worth retrying? Real providers: DNS + TCP to their API host. Mock: not failing."""
        from .telemetry.recorder import probe_host

        host = PROVIDER_HOSTS.get(name)
        if host is None:
            try:
                p = self.providers.get(name)
            except Exception:
                return False
            return getattr(p, "fail_mode", "none") != "unavailable"
        return bool((await probe_host(host, timeout=3.0)).get("ok"))

    def _audio_event(self, kind: str, data: dict) -> None:
        self.telemetry.record(kind, data, session_id=data.get("session_id"), capture_id=data.get("capture_id"))

    def session_root(self, session_id: str) -> Path:
        return self.settings.sessions_dir / session_id

    def apply_prefs(self) -> None:
        """Push the owner's audio preferences into the live speech and cue players."""
        p = self.prefs.current
        if isinstance(self.speech, SaySpeech | CompanionSpeech):
            self.speech.rate = p.speech_rate_wpm
        if isinstance(self.cues, CuePlayer):
            self.cues.sounds["received"] = sound_path(p.received_sound)
            self.cues.volume = p.cue_volume

    async def _speech_mark(self, stage: str, meta: dict) -> None:
        if meta.get("capture_id") and meta.get("kind") == "advice":
            await self.timer.mark(stage, session_id=meta.get("session_id"), capture_id=meta["capture_id"],
                                  assessment_id=meta.get("assessment_id"))
        elif meta.get("voice_turn_id"):
            await self.timer.mark(stage, session_id=meta.get("session_id"), voice_turn_id=meta["voice_turn_id"])

    # --- lifecycle -----------------------------------------------------------------------
    async def start(self, *, watch: bool = True) -> None:
        await self.projects.ensure_defaults()
        self.coaching.preferences_source = lambda session: self.projects.preferences_for(
            session, self.prefs.current.my_preferences)
        # Assessments interrupted by a previous shutdown are failed, never replayed or spoken.
        for a in await self.store.query(Assessment, "status IN ('queued','running')"):
            a.status, a.error, a.speech_status = "failed", "interrupted by restart", "not_applicable"
            await self.store.put(a)
        for s in await self.store.list_sessions():
            await self._load_context(s)
        if await self.store.query(Capture, "json_extract(data, '$.retry_when_online') = 1"):
            self.coaching.poke_online()
        active = await self.active_session()
        if watch and active:
            await self.ingest.watch(active, startup=True)
        if self.settings.global_keys in ("pynput", "gamepad"):
            await self.start_global_keys()
        self.telemetry.record("app.started", startup_snapshot(
            self.settings, {"schema_version": self.store_sync.schema_version(), "log_file": str(self.log_path),
                            "active_session": active.id if active else None, "speech": self.speech.name,
                            "recorder": self.voice.recorder.name, "transcriber": self.voice.transcriber.name}),
            session_id=active.id if active else None)
        if isinstance(self.voice.recorder, ContinuousRecorder):
            self._mic_task = asyncio.create_task(self._mic_watchdog(self.voice.recorder))
        self.network.start()
        self.camera.start(asyncio.get_running_loop())
        self.started = True

    async def _mic_watchdog(self, rec: ContinuousRecorder, every_s: float = 2.0) -> None:
        """Always-open mic: open it, keep it open (reopen after the headphones come back), report changes."""
        loop = asyncio.get_running_loop()
        was: tuple | None = None
        while True:
            ok = await loop.run_in_executor(None, rec.ensure_open)
            now = (ok, rec.reopened, rec.last_error, rec.last_stall)
            if now != was:
                st = rec.status()
                self.bus.publish("mic.status", **st)
                self.telemetry.record("mic.status", st)
                was = now
            await asyncio.sleep(every_s)

    async def stop(self) -> None:
        # Hand the camera back first so its own buttons work even if the rest of shutdown is slow.
        await asyncio.get_running_loop().run_in_executor(None, self.camera.stop)
        if self._mic_task:
            self._mic_task.cancel()
        if isinstance(self.voice.recorder, ContinuousRecorder):
            self.voice.recorder.close()
        await self.network.stop()
        self.telemetry.record("app.stopping", {})
        if self.keys:
            self.keys.stop()
        await self.voice.cancel("shutdown") if self.voice.state.value == "listening" else None
        await self.audio.stop("shutdown")
        await self.ingest.close()
        await self.coaching.drain(timeout=2)
        if self.coaching._online_task:
            self.coaching._online_task.cancel()
        for t in list(self.coaching.tasks):
            t.cancel()
        await self.telemetry.flush()
        self.metadata.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.store.shutdown()

    async def _load_context(self, s: Session) -> None:
        self.tracker.set_active_shot(s.id, s.active_shot_id, initial=True)
        self.tracker.get(s.id).setup_revision_id = s.current_setup_revision_id
        for c in await self.store.captures(s.id):
            if c.processing_state not in ("discovered", "stabilizing"):
                self.tracker.capture_ready(s.id, c.shot_id, c.id, c.seq, self.tracker.later_bracket_frame(c.exif))

    # --- camera control ------------------------------------------------------------------------
    async def _camera_cue(self, kind: str) -> None:
        """Ticks through the companion app (~50 ms) when it's running, else afplay (~170 ms)."""
        path = self.settings.camera_tick_sound if kind == "camera_tick" else self.settings.camera_end_sound
        if isinstance(self.speech, CompanionSpeech) and await self.speech.cue(path):
            return
        self.cues.play(kind)

    async def camera_suggestion(self) -> tuple[str, str] | None:
        """The coach's one camera-side change for the newest photo, as (setting, value), when it's machine-readable.
        For now that's the aperture in the exposure starting point; a structured field comes with the prompt change."""
        active = await self.active_session()
        if not active:
            return None
        for c in reversed(await self.store.captures(active.id)):
            a = await self.store.latest_completed_assessment(c.id)
            if a is None:
                continue
            note = a.exposure_note or {}
            f = note.get("new_f_number")
            return ("aperture", f"{float(f):.1f}") if note.get("applicable") and f else None
        return None

    async def apply_camera_suggestion(self) -> str:
        from .camera import settings as S

        s = await self.camera_suggestion()
        if s is None:
            return "Nothing to apply from the last photo."
        setting, value = s
        before = self.camera.values.get(setting)
        r = await self.camera.set_value(setting, value, source="coach")
        self.bus.publish("camera.applied", setting=setting, before=before, after=r["value"],
                         display=r["display"], clamped=r["clamped"])
        if r["clamped"]:
            return f"{S.spoken(setting, r['value'])}: the lens can't go to {S.display(setting, value)}."  # type: ignore[arg-type]
        return f"{r['spoken']}, applied."

    async def on_remote_button(self, name: str, down: bool) -> None:
        if self.camera.mode == "off":
            return
        if down:
            await self.remote_camera.press(name)
        else:
            await self.remote_camera.release(name)

    async def start_global_keys(self) -> None:
        from .input.gamepad import GamepadListener
        from .input.global_keys import GlobalKeyListener

        async def dispatch(action: str) -> None:
            active = await self.active_session()
            sid = active.id if active else None
            if action == "press":
                await self.voice.press(sid, source="global_key")
            elif action == "release":
                await self.voice.release(source="global_key")
            elif action == "toggle":
                await self.voice.toggle(sid, source="global_key")
            elif action == "cancel":
                await self.voice.cancel("cancel key")
            elif action == "pause_toggle" and sid:
                s = await self.set_coaching_paused(sid, not active.coaching_paused, reason="paused by remote key")
                msg = "Coaching paused." if s.coaching_paused else "Coaching resumed."
                await self.audio.speak(msg, lambda: True, {"session_id": sid, "kind": "notice"})
            elif action == "learned":
                self.bus.publish("keys.learned", key=self.keys.tracker.learned if self.keys else None)

        s = self.settings
        if s.global_keys == "gamepad":
            self.keys = GamepadListener(s.gamepad_ptt, s.gamepad_cancel, s.ptt_mode, dispatch,
                                        self.voice.listener_failed, s.gamepad_pause, on_button=self.on_remote_button)
        else:
            self.keys = GlobalKeyListener(s.ptt_key, s.cancel_key, s.ptt_mode, dispatch, self.voice.listener_failed,
                                          s.pause_key)
        loop = asyncio.get_running_loop()
        self.keys.tracker.on_log = lambda entry: loop.call_soon_threadsafe(
            self.telemetry.record, "keys.event", {**entry, "mode": self.settings.ptt_mode, "source": "global"})
        self.keys.start(loop)
        self.telemetry.record("keys.listener", {"running": self.keys.running, "error": self.keys.error,
                                                 "source": s.global_keys, "mode": s.ptt_mode,
                                                 "ptt_key": s.gamepad_ptt if s.global_keys == "gamepad" else s.ptt_key})

    # --- sessions ------------------------------------------------------------------------
    async def active_session(self) -> Session | None:
        for s in await self.store.query(Session, order="rowid DESC"):
            if s.status == SessionStatus.active:
                return s
        return None

    async def get_session(self, session_id: str) -> Session:
        s = await self.store.get(Session, session_id)
        if s is None:
            raise NotFound(f"session {session_id}")
        return s

    async def create_session(self, *, name: str, product: str = "", watch_folder: str | None = None,
                             template: str | None = "running_shoe", assess_provider: str | None = None,
                             teaching_mode: bool = True, setup: dict | None = None, simulated: bool = False,
                             ui_theme: str = "studio", template_id: str | None = None,
                             project_id: str | None = None, shoot_preferences: str = "") -> Session:
        tpl = await self.projects.template(template_id) if template_id else (
            await self.projects.template_for_key(template) if template in TEMPLATES else None)
        s = Session(name=name, product=product, output_folder="", assess_provider=assess_provider or self.settings.assess_provider,
                    teaching_mode=teaching_mode, simulated=simulated, ui_theme=ui_theme,
                    template=(tpl.source or "custom") if tpl else (template if template in TEMPLATES else "empty"),
                    project_id=project_id or (tpl.project_id if tpl else None),
                    template_id=tpl.id if tpl else None, template_version=tpl.version if tpl else None,
                    shoot_preferences=(shoot_preferences or "").strip())
        s.output_folder = str(self.session_root(s.id))
        s.watch_folder = str(Path(watch_folder).expanduser()) if watch_folder else str(self.settings.data_dir / "incoming" / s.id)
        Path(s.output_folder).mkdir(parents=True, exist_ok=True)
        # Only one active session is watched: pause the others.
        for other in await self.store.list_sessions():
            if other.status == SessionStatus.active:
                other.status = SessionStatus.paused
                other.updated_at = utcnow()
                await self.store.put(other)
        await self.store.put(s)
        rev = SetupRevision(session_id=s.id, revision=1, **SetupFields(**(setup or {})).model_dump())
        await self.store.put(rev)
        s.current_setup_revision_id = rev.id
        if tpl:
            for i, shot in enumerate(tpl.shots):
                await self.store.put(ShotRequirement(session_id=s.id, ordinal=i, **template_shot_fields(shot)))
        elif template in TEMPLATES:
            for i, shot in enumerate(template_shots(template)):
                await self.store.put(ShotRequirement(session_id=s.id, ordinal=i, **shot))
        shots = await self.store.shots(s.id)
        s.active_shot_id = shots[0].id if shots else None
        await self.store.put(s)
        await self._load_context(s)
        await self.ingest.watch(s)
        self.bus.publish("session.created", session_id=s.id)
        return s

    async def update_session(self, session_id: str, patch: dict[str, Any]) -> Session:
        s = await self.get_session(session_id)
        allowed = {"name", "product", "watch_folder", "assess_provider", "teaching_mode", "status",
                   "coaching_paused", "budget_usd", "max_model_calls", "ui_theme", "shoot_preferences"}
        rewatch = False
        for k, v in patch.items():
            if k not in allowed:
                raise ValueError(f"field {k} is not editable here")
            if k == "watch_folder":
                v = str(Path(v).expanduser())
                rewatch = True
                s.watch_since = utcnow()
            if k == "status" and v == SessionStatus.active and s.status != SessionStatus.active:
                rewatch = True
                for other in await self.store.list_sessions():
                    if other.id != s.id and other.status == SessionStatus.active:
                        other.status = SessionStatus.paused
                        await self.store.put(other)
            setattr(s, k, v)
        s.updated_at = utcnow()
        await self.store.put(s)
        if s.status != SessionStatus.active and self.ingest.watched_session_id == s.id:
            await self.ingest.stop_watching()
        elif rewatch and s.status == SessionStatus.active:
            await self.ingest.watch(s)
        self.bus.publish("session.updated", session_id=s.id)
        return s

    # --- coaching control, feedback, cues ----------------------------------------------------
    async def set_coaching_paused(self, session_id: str, paused: bool, reason: str | None = None) -> Session:
        s = await self.get_session(session_id)
        if paused:
            s.coaching_paused, s.paused_reason = True, reason or "paused"
        else:
            summary = await self.usage(session_id)
            if summary["exceeded"]:
                s.coaching_paused, s.paused_reason = True, f"budget: {summary['reason']}"
            else:
                s.coaching_paused, s.paused_reason = False, None
        s.updated_at = utcnow()
        await self.store.put(s)
        self.bus.publish("session.coaching", session_id=session_id, paused=s.coaching_paused, reason=s.paused_reason)
        return s

    async def usage(self, session_id: str) -> dict:
        from .coaching.budget import usage_summary

        s = await self.get_session(session_id)
        return usage_summary(await self.store.model_calls(session_id), s, self.settings)

    async def _budget_exceeded(self, session_id: str, reason: str) -> None:
        s = await self.get_session(session_id)
        if s.coaching_paused and (s.paused_reason or "").startswith("budget"):
            return  # already paused for budget: announce once
        await self.set_coaching_paused(session_id, True, reason=f"budget: {reason}")
        await self.audio.speak("Coaching paused: the session budget is used up. Photos are still saved.",
                               lambda: True, {"session_id": session_id, "kind": "notice"})

    async def experiment_for_feedback(self, session_id: str, capture: Capture | None):
        """The experiment a spoken rating refers to: the one this photo followed up, else the latest advice."""
        exps = await self.store.experiments(session_id)
        if capture:
            for e in reversed(exps):
                if e.follow_up_capture_id == capture.id:
                    return e
            for e in reversed(exps):
                if e.baseline_capture_id == capture.id:
                    return e
            shot_exps = [e for e in exps if e.shot_id == capture.shot_id]
            if shot_exps:
                return shot_exps[-1]
        return exps[-1] if exps else None

    async def update_experiment(self, experiment_id: str, patch: dict[str, Any]):
        from .domain.models import Experiment

        def apply(e: Experiment) -> None:
            for k, v in patch.items():
                setattr(e, k, v)

        e = await self.store.update(Experiment, experiment_id, apply)
        if e is None:
            raise NotFound(f"experiment {experiment_id}")
        self.bus.publish("experiment.updated", session_id=e.session_id, experiment_id=e.id, **patch)
        return e

    async def set_change_note(self, session_id: str, text: str | None) -> str | None:
        ctx = self.tracker.get(session_id)
        ctx.pending_change = (text or "").strip() or None
        self.bus.publish("session.change_note", session_id=session_id, text=ctx.pending_change)
        return ctx.pending_change

    def _cue_sink(self, event: dict) -> None:
        """Audible confirmations for someone looking through the camera, not at the screen."""
        mode = self.settings.received_cue
        if mode == "none":
            return
        t, p = event["type"], event.get("payload") or {}
        if t == "capture.ready" and not p.get("recovered"):
            if mode == "speech" and not self.audio.speaking:
                task = asyncio.get_running_loop().create_task(self.audio.speak(
                    f"Got {p.get('seq')}.", lambda: True,
                    {"session_id": event.get("session_id"), "capture_id": event.get("capture_id"), "kind": "cue"}))
                self.coaching.tasks.add(task)
                task.add_done_callback(self.coaching.tasks.discard)
            else:
                self.cues.play("received")
        elif t in ("capture.failed", "capture.ingest_failed") or (
                t == "analysis.failed" and not str(p.get("error", "")).startswith("Budget")):
            self.cues.play("failure")

    async def set_active_shot(self, session_id: str, shot_id: str | None) -> Session:
        s = await self.get_session(session_id)
        if shot_id is not None:
            shot = await self.store.get(ShotRequirement, shot_id)
            if shot is None or shot.session_id != session_id:
                raise NotFound(f"shot {shot_id}")
        s.active_shot_id = shot_id
        s.updated_at = utcnow()
        await self.store.put(s)
        self.tracker.set_active_shot(session_id, shot_id)
        await self.audio.invalidate()  # advice for the previous shot must not keep playing
        self.bus.publish("session.active_shot", session_id=session_id, shot_id=shot_id)
        return s

    async def advance_shot(self, session_id: str) -> ShotRequirement | None:
        from .coverage import compute_coverage

        s = await self.get_session(session_id)
        cov = await compute_coverage(self.store, session_id, verify=False)
        order = [x["shot_id"] for x in cov["shots"]]
        unresolved = [x["shot_id"] for x in cov["shots"] if not x["resolved"]]
        if not unresolved:
            return None
        start = order.index(s.active_shot_id) + 1 if s.active_shot_id in order else 0
        rotated = order[start:] + order[:start]
        nxt = next(i for i in rotated if i in unresolved)
        await self.set_active_shot(session_id, nxt)
        return await self.store.get(ShotRequirement, nxt)

    async def add_shot(self, session_id: str, data: dict[str, Any]) -> ShotRequirement:
        await self.get_session(session_id)
        existing = await self.store.shots(session_id)
        shot = ShotRequirement(session_id=session_id, ordinal=len(existing), **data)
        await self.store.put(shot)
        self.bus.publish("shot.updated", session_id=session_id, shot_id=shot.id, created=True)
        return shot

    async def update_shot(self, shot_id: str, patch: dict[str, Any]) -> ShotRequirement:
        shot = await self.store.get(ShotRequirement, shot_id)
        if shot is None:
            raise NotFound(f"shot {shot_id}")
        editable = {"title", "purpose", "must_show", "framing", "sharp_regions", "criteria", "reference_image",
                    "needs_retake", "ordinal"}
        data = shot.model_dump()
        for k, v in patch.items():
            if k not in editable:
                raise ValueError(f"field {k} is not editable")
            data[k] = v
        data["updated_at"] = utcnow()
        new = ShotRequirement.model_validate(data)
        ids = [c.id for c in new.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("criterion ids must be unique")
        await self.store.put(new)
        self.bus.publish("shot.updated", session_id=new.session_id, shot_id=new.id)
        return new

    async def update_setup(self, session_id: str, fields: dict[str, Any]) -> SetupRevision:
        s = await self.get_session(session_id)
        revs = await self.store.setup_revisions(session_id)
        base = revs[-1].model_dump(include=set(SetupFields.model_fields)) if revs else {}
        base.update(fields)
        rev = SetupRevision(session_id=session_id, revision=(revs[-1].revision + 1 if revs else 1),
                            **SetupFields(**base).model_dump())
        await self.store.put(rev)
        s.current_setup_revision_id = rev.id
        s.updated_at = utcnow()
        await self.store.put(s)
        self.tracker.get(session_id).setup_revision_id = rev.id
        self.bus.publish("session.setup", session_id=session_id, revision=rev.revision)
        return rev

    async def update_capture(self, capture_id: str, patch: dict[str, Any]) -> Capture:
        cap = await self.store.get(Capture, capture_id)
        if cap is None:
            raise NotFound(f"capture {capture_id}")
        if "shot_id" in patch:
            shot_id = patch["shot_id"]
            if shot_id is not None:
                shot = await self.store.get(ShotRequirement, shot_id)
                if shot is None or shot.session_id != cap.session_id:
                    raise NotFound(f"shot {shot_id}")
            cap.shot_id = shot_id
            cap.attribution_ambiguous = False
            if shot_id:
                self.tracker.capture_ready(cap.session_id, shot_id, cap.id, cap.seq,
                                           self.tracker.later_bracket_frame(cap.exif))
        if "extra_shot_ids" in patch:
            cap.extra_shot_ids = list(dict.fromkeys(patch["extra_shot_ids"]))
        if "baseline_capture_id" in patch:
            b = patch["baseline_capture_id"]
            if b is not None:
                other = await self.store.get(Capture, b)
                if other is None or other.session_id != cap.session_id or other.id == cap.id:
                    raise ValueError("invalid baseline capture")
            cap.baseline_capture_id = b
            cap.baseline_overridden = True
        if "user_reported_change" in patch:
            cap.user_reported_change = patch["user_reported_change"]
        await self.store.put(cap)
        self.bus.publish("capture.updated", session_id=cap.session_id, capture_id=cap.id)
        return cap
