"""Application container: constructs adapters/services and owns session-level operations."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .audio.recording import (
    MockRecorder,
    MockTranscriber,
    OpenAITranscriber,
    Recorder,
    SoundDeviceRecorder,
    Transcriber,
)
from .audio.speech import AudioController, MockSpeech, NullSpeech, SaySpeech, SpeechBackend
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
from .templates import shoe_shots

log = logging.getLogger(__name__)


class NotFound(Exception):
    pass


def build_speech(settings: Settings) -> SpeechBackend:
    if settings.speech_provider == "say":
        return SaySpeech(settings.say_voice, settings.say_rate_wpm, settings.say_audio_device)
    if settings.speech_provider == "mock":
        return MockSpeech()
    return NullSpeech()


def build_recorder(settings: Settings) -> Recorder:
    if settings.recorder == "sounddevice":
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
                 transcriber: Transcriber | None = None, store: Store | None = None):
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
        self.ingest = IngestService(store=self.store, bus=self.bus, timer=self.timer, settings=settings,
                                    tracker=self.tracker, executor=self.executor, metadata=self.metadata,
                                    on_ready=self.coaching.on_capture_ready)
        self.voice = VoiceController(store=self.store, bus=self.bus, settings=settings, tracker=self.tracker,
                                     audio=self.audio, recorder=recorder or build_recorder(settings),
                                     transcriber=transcriber or build_transcriber(settings), app=self)
        self.keys = None
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

    def _audio_event(self, kind: str, data: dict) -> None:
        self.telemetry.record(kind, data, session_id=data.get("session_id"), capture_id=data.get("capture_id"))

    def session_root(self, session_id: str) -> Path:
        return self.settings.sessions_dir / session_id

    async def _speech_mark(self, stage: str, meta: dict) -> None:
        if meta.get("capture_id") and meta.get("kind") == "advice":
            await self.timer.mark(stage, session_id=meta.get("session_id"), capture_id=meta["capture_id"],
                                  assessment_id=meta.get("assessment_id"))
        elif meta.get("voice_turn_id"):
            await self.timer.mark(stage, session_id=meta.get("session_id"), voice_turn_id=meta["voice_turn_id"])

    # --- lifecycle -----------------------------------------------------------------------
    async def start(self, *, watch: bool = True) -> None:
        # Assessments interrupted by a previous shutdown are failed, never replayed or spoken.
        for a in await self.store.query(Assessment, "status IN ('queued','running')"):
            a.status, a.error, a.speech_status = "failed", "interrupted by restart", "not_applicable"
            await self.store.put(a)
        for s in await self.store.list_sessions():
            await self._load_context(s)
        active = await self.active_session()
        if watch and active:
            await self.ingest.watch(active, startup=True)
        if self.settings.global_keys == "pynput":
            await self.start_global_keys()
        self.telemetry.record("app.started", startup_snapshot(
            self.settings, {"schema_version": self.store_sync.schema_version(), "log_file": str(self.log_path),
                            "active_session": active.id if active else None, "speech": self.speech.name,
                            "recorder": self.voice.recorder.name, "transcriber": self.voice.transcriber.name}),
            session_id=active.id if active else None)
        self.network.start()
        self.started = True

    async def stop(self) -> None:
        await self.network.stop()
        self.telemetry.record("app.stopping", {})
        if self.keys:
            self.keys.stop()
        await self.voice.cancel("shutdown") if self.voice.state.value == "listening" else None
        await self.audio.stop("shutdown")
        await self.ingest.close()
        await self.coaching.drain(timeout=2)
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
                self.tracker.capture_ready(s.id, c.shot_id, c.id, c.seq)

    async def start_global_keys(self) -> None:
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
            elif action == "learned":
                self.bus.publish("keys.learned", key=self.keys.tracker.learned if self.keys else None)

        self.keys = GlobalKeyListener(self.settings.ptt_key, self.settings.cancel_key, self.settings.ptt_mode,
                                      dispatch, self.voice.listener_failed)
        loop = asyncio.get_running_loop()
        self.keys.tracker.on_log = lambda entry: loop.call_soon_threadsafe(
            self.telemetry.record, "keys.event", {**entry, "mode": self.settings.ptt_mode, "source": "global"})
        self.keys.start(loop)
        self.telemetry.record("keys.listener", {"running": self.keys.running, "error": self.keys.error,
                                                 "ptt_key": self.settings.ptt_key, "mode": self.settings.ptt_mode})

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
                             teaching_mode: bool = True, setup: dict | None = None, simulated: bool = False) -> Session:
        s = Session(name=name, product=product, output_folder="", assess_provider=assess_provider or self.settings.assess_provider,
                    teaching_mode=teaching_mode, simulated=simulated)
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
        if template == "running_shoe":
            for i, shot in enumerate(shoe_shots()):
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
        allowed = {"name", "product", "watch_folder", "assess_provider", "teaching_mode", "status"}
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
                self.tracker.capture_ready(cap.session_id, shot_id, cap.id, cap.seq)
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
