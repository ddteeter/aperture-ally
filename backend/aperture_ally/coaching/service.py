"""Coaching orchestration: evidence → model → validation → experiment linkage → guarded speech.

Scheduling policy
* Every capture is ingested and kept. Automatic coaching targets the newest ready capture of the
  active shot. At most one automatic request is *queued* per session (newer replaces older); running
  requests finish and are stored for history, but their speech is suppressed if no longer current.
* Explicit user reviews are never coalesced.
* In-camera brackets: only the base frame (shot 1) is auto-coached; later frames neither trigger coaching
  nor cut off the base frame's advice.
* No backlog replay: failed/unavailable assessments stay failed until the user retries.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import Executor
from pathlib import Path
from typing import Any

from ..config import Settings
from ..domain.assessment import (
    AssessmentResult,
    ConversationAnswer,
    ValidationContext,
    provider_json_schema,
    validate_output,
)
from ..domain.exposure import ExposureContext, exposure_note_for
from ..domain.models import (
    Assessment,
    Capture,
    Experiment,
    ProcessingState,
    Session,
    SetupRevision,
    ShotRequirement,
    utcnow,
)
from ..events import EventBus
from ..imaging.measurements import region_comparable
from ..imaging.pipeline import ensure_evidence
from ..runtime import ContextTracker, Guard
from ..telemetry.timing import Timer
from .budget import BudgetExceeded, usage_summary
from .prompt import (
    ANSWER_PROMPT_VERSION,
    PROMPT_VERSION,
    SPOKEN_FIRST_NOTE,
    SYSTEM_ANSWER,
    SYSTEM_ASSESS,
    ImageInput,
    ModelRequest,
    compact_measurements,
    metadata_for_model,
)
from .providers.base import Provider, ProviderError, ProviderUnavailable, estimate_cost, unavailable_message
from .streaming import completed_string_field, spoken_first_schema

log = logging.getLogger(__name__)

FRAME_OF_REFERENCE = "camera-left/right = the photographer's left/right while looking through the camera"


class ProviderRegistry:
    def __init__(self, settings: Settings, overrides: dict[str, Provider] | None = None):
        self.settings = settings
        self._cache: dict[str, Provider] = dict(overrides or {})
        self.health: dict[str, dict[str, Any]] = {}

    def get(self, name: str) -> Provider:
        if name in self._cache:
            return self._cache[name]
        s = self.settings
        if name == "mock":
            from .providers.mock import MockProvider

            p: Provider = MockProvider()
        elif name == "openai":
            if not s.openai_api_key or not s.openai_model:
                raise ProviderUnavailable("OpenAI not configured: set OPENAI_API_KEY and APERTURE_ALLY_OPENAI_MODEL")
            from .providers.openai_adapter import OpenAIProvider

            p = OpenAIProvider(s.openai_api_key.get_secret_value(), s.openai_model,
                               image_detail=s.openai_image_detail, timeout_s=s.model_timeout_s,
                               effort=s.openai_effort)
        elif name == "gemini":
            if not s.gemini_api_key or not s.gemini_model:
                raise ProviderUnavailable("Gemini not configured: set GEMINI_API_KEY and APERTURE_ALLY_GEMINI_MODEL")
            from .providers.gemini_adapter import GeminiProvider

            p = GeminiProvider(s.gemini_api_key.get_secret_value(), s.gemini_model,
                               media_resolution=s.gemini_media_resolution, timeout_s=s.model_timeout_s,
                               thinking_level=s.gemini_thinking_level)
        elif name == "claude":
            if not s.claude_model:
                raise ProviderUnavailable("Claude not configured: set APERTURE_ALLY_CLAUDE_MODEL")
            from .providers.claude_adapter import ClaudeProvider

            # No key → the SDK resolves ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile itself.
            p = ClaudeProvider(s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else None,
                               s.claude_model, effort=s.claude_effort, timeout_s=s.model_timeout_s,
                               refusal_fallback=s.claude_refusal_fallback)
        else:
            raise ProviderUnavailable(f"unknown provider {name}")
        self._cache[name] = p
        return p

    def configured(self) -> dict[str, bool]:
        s = self.settings
        return {"mock": True, "openai": bool(s.openai_api_key and s.openai_model),
                "gemini": bool(s.gemini_api_key and s.gemini_model),
                "claude": bool(s.anthropic_api_key and s.claude_model)}


class CoachingService:
    def __init__(self, *, store, bus: EventBus, timer: Timer, settings: Settings, tracker: ContextTracker,
                 executor: Executor, providers: ProviderRegistry, audio, session_root, recorder):
        self.store = store
        self.bus = bus
        self.timer = timer
        self.settings = settings
        self.tracker = tracker
        self.executor = executor
        self.providers = providers
        self.audio = audio
        self.session_root = session_root
        self.recorder = recorder
        self.on_budget_exceeded = None  # async callback(session_id, reason) set by the app container
        self._sem = asyncio.Semaphore(settings.max_model_concurrency)
        self._pending_auto: dict[str, str] = {}
        self._running_auto: dict[str, set[asyncio.Task]] = {}
        self._inflight: dict[str, asyncio.Task] = {}  # capture_id -> latest assessment task
        self._capture_tasks: dict[str, set[asyncio.Task]] = {}  # capture_id -> every running assessment task
        self.tasks: set[asyncio.Task] = set()
        # Retry-when-online: async (provider_name) -> bool, set by the app container (network probe / mock state).
        self.reachable = None
        self._online_task: asyncio.Task | None = None
        self._online_poke = asyncio.Event()

    # --- scheduling ----------------------------------------------------------------------
    async def on_capture_ready(self, capture: Capture, auto: bool) -> None:
        bracket = (capture.exif or {}).get("bracket")
        if bracket and bracket.get("shot", 1) > 1:
            # Later frames of an in-camera bracket: the base frame (shot 1) is the one coached, and its advice
            # keeps playing while the rest of the set arrives. "Review anyway" still works on any frame.
            if auto and self.settings.auto_coach and not capture.recovered:
                self.bus.publish("analysis.skipped", session_id=capture.session_id, capture_id=capture.id,
                                 reason=f"{bracket.get('kind', '')} bracket frame {bracket['shot']}: coaching the base frame")
            return
        await self.audio.invalidate()  # a new photo makes older automatic advice obsolete
        if not auto or not self.settings.auto_coach or capture.recovered:
            return
        session = await self.store.get(Session, capture.session_id)
        if session and session.coaching_paused:
            self.bus.publish("analysis.skipped", session_id=capture.session_id, capture_id=capture.id,
                             reason=session.paused_reason or "coaching paused")
            return
        ctx = self.tracker.get(capture.session_id)
        if capture.shot_id is None or capture.shot_id != ctx.active_shot_id:
            return
        prev = self._pending_auto.get(capture.session_id)
        if prev and prev != capture.id:
            self.bus.publish("analysis.coalesced", session_id=capture.session_id, capture_id=prev,
                             superseded_by=capture.id)
        self._pending_auto[capture.session_id] = capture.id
        self._pump(capture.session_id)

    def _pump(self, session_id: str) -> None:
        running = self._running_auto.setdefault(session_id, set())
        while session_id in self._pending_auto and len(running) < self.settings.max_model_concurrency:
            cid = self._pending_auto.pop(session_id)
            task = self._spawn(self.run_assessment(cid, trigger="auto"), capture_id=cid)
            running.add(task)

            def done(t: asyncio.Task, sid: str = session_id) -> None:
                self._running_auto.get(sid, set()).discard(t)
                self._pump(sid)

            task.add_done_callback(done)

    def _spawn(self, coro, capture_id: str | None = None) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        if capture_id:
            self._inflight[capture_id] = task
            task.add_done_callback(lambda _t: self._inflight.pop(capture_id, None) if self._inflight.get(capture_id) is _t else None)
            group = self._capture_tasks.setdefault(capture_id, set())
            group.add(task)

            def forget(t: asyncio.Task) -> None:
                group.discard(t)
                if not group and self._capture_tasks.get(capture_id) is group:
                    self._capture_tasks.pop(capture_id, None)

            task.add_done_callback(forget)
        return task

    # --- cancel / retry ------------------------------------------------------------------
    async def cancel(self, capture_id: str) -> bool:
        """Cancel queued/running analysis of this capture. The provider result, if it still arrives, is dropped
        (the awaiting task is gone) and never spoken; speech about this capture is stopped."""
        cap = await self.store.get(Capture, capture_id)
        if cap is None:
            return False
        cancelled = False
        if self._pending_auto.get(cap.session_id) == capture_id:
            self._pending_auto.pop(cap.session_id)
            cancelled = True
        tasks = [t for t in self._capture_tasks.get(capture_id, set()) if not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            cancelled = True
            await asyncio.wait(tasks, timeout=2)
        for a in await self.store.assessments_for(capture_id):
            if a.status in ("queued", "running"):
                a.status, a.error, a.speech_status = "superseded", "cancelled by user", "cancelled"
                a.completed_at = utcnow()
                await self.store.put(a)
                cancelled = True
            elif a.speech_status == "pending" and tasks:
                a.speech_status = "cancelled"
                await self.store.put(a)
        cur = self.audio.current
        if cur is not None and cur.meta.get("capture_id") == capture_id:
            await self.audio.stop("analysis cancelled")
            cancelled = True
        if cancelled:
            done = await self.store.latest_completed_assessment(capture_id)

            def restore(c: Capture) -> None:
                if c.processing_state in (ProcessingState.analyzing, ProcessingState.ready):
                    c.processing_state = ProcessingState.analyzed if done else ProcessingState.ready
                    c.error = None

            await self.store.update(Capture, capture_id, restore)
            self.bus.publish("analysis.cancelled", session_id=cap.session_id, capture_id=capture_id)
        return cancelled

    async def arm_retry_online(self, capture_id: str) -> Capture | None:
        """Run this capture's assessment once, automatically, when the provider is reachable again."""
        def arm(c: Capture) -> None:
            c.retry_when_online = True

        cap = await self.store.update(Capture, capture_id, arm)
        if cap is None:
            return None
        self.bus.publish("analysis.retry_armed", session_id=cap.session_id, capture_id=cap.id)
        self.poke_online()
        return cap

    def poke_online(self) -> None:
        """Check armed retries now (e.g. after a successful network probe); starts the watcher if needed."""
        if self._online_task is None or self._online_task.done():
            self._online_task = asyncio.create_task(self._watch_online())  # not in self.tasks: drain() ignores it
        else:
            self._online_poke.set()

    async def _watch_online(self) -> None:
        while True:
            try:
                armed = await self.store.query(Capture, "json_extract(data, '$.retry_when_online') = 1")
                if not armed:
                    return
                for sid in {c.session_id for c in armed}:
                    session = await self.store.get(Session, sid)
                    if session and (self.reachable is None or await self.reachable(session.assess_provider)):
                        await self.run_armed(sid)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("retry-when-online check failed")
            self._online_poke.clear()
            try:
                await asyncio.wait_for(self._online_poke.wait(), self.settings.retry_online_poll_s)
            except TimeoutError:
                pass

    async def run_armed(self, session_id: str) -> list[str]:
        """Provider is back: run the newest armed capture of each shot (older ones are disarmed, no backlog)."""
        armed = [c for c in await self.store.captures(session_id) if c.retry_when_online]
        newest: dict[str | None, Capture] = {}
        for c in armed:
            if c.shot_id not in newest or c.seq > newest[c.shot_id].seq:
                newest[c.shot_id] = c
        started = []
        for c in armed:
            def disarm(x: Capture) -> None:
                x.retry_when_online = False

            await self.store.update(Capture, c.id, disarm)
            if newest.get(c.shot_id) is c:
                guard = self.tracker.auto_guard(session_id, c.shot_id, c.id)  # speak only if still current
                self._spawn(self.run_assessment(c.id, trigger="user", guard=guard), capture_id=c.id)
                started.append(c.id)
                self.bus.publish("analysis.retry_online", session_id=session_id, capture_id=c.id)
            else:
                self.bus.publish("analysis.retry_dropped", session_id=session_id, capture_id=c.id,
                                 reason="a newer photo of this shot is retried instead")
        return started

    def request_review(self, capture_id: str, *, baseline_capture_id: str | None = None,
                       kind: str | None = None, speak: bool = True) -> asyncio.Task:
        return self._spawn(self.run_assessment(capture_id, trigger="user", baseline_override=baseline_capture_id,
                                               kind=kind, speak=speak), capture_id=capture_id)

    async def wait_inflight(self, capture_id: str, timeout: float) -> None:
        t = self._inflight.get(capture_id)
        if t:
            try:
                await asyncio.wait_for(asyncio.shield(t), timeout)
            except (TimeoutError, Exception):
                pass

    async def drain(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while self.tasks and time.monotonic() < deadline:
            await asyncio.wait(list(self.tasks), timeout=max(0.01, deadline - time.monotonic()))

    # --- baseline selection --------------------------------------------------------------
    async def default_baseline(self, capture: Capture) -> str | None:
        """Last *coached* capture (completed assessment with an action) of the same shot, before this one."""
        if not capture.shot_id:
            return None
        for prev in reversed(await self.store.captures(capture.session_id, capture.shot_id)):
            if prev.seq >= capture.seq:
                continue
            a = await self.store.latest_completed_assessment(prev.id)
            if a and a.result and a.result.get("primary_action"):
                return prev.id
        return None

    # --- the assessment ------------------------------------------------------------------
    async def run_assessment(self, capture_id: str, *, trigger: str = "auto", baseline_override: str | None = None,
                             kind: str | None = None, speak: bool = True, provider_name: str | None = None,
                             guard: Guard | None = None) -> Assessment | None:
        capture = await self.store.get(Capture, capture_id)
        if capture is None:
            return None
        session = await self.store.get(Session, capture.session_id)
        assert session is not None
        shot = await self.store.get(ShotRequirement, capture.shot_id) if capture.shot_id else None
        setup = await self.store.get(SetupRevision, capture.setup_revision_id) if capture.setup_revision_id else None
        if trigger == "auto":
            guard = guard or self.tracker.auto_guard(session.id, capture.shot_id, capture.id)
        elif trigger == "user":
            guard = guard or self.tracker.user_guard(session.id)
        else:
            guard = guard or (lambda: False)

        # Baseline: explicit override > capture's user override > default (last coached, same shot).
        if baseline_override:
            baseline_id = baseline_override
        elif capture.baseline_overridden:
            baseline_id = capture.baseline_capture_id
        elif kind == "assess":
            baseline_id = None
        else:
            baseline_id = await self.default_baseline(capture)
        if baseline_id == capture.id:
            baseline_id = None
        if not capture.baseline_overridden and capture.baseline_capture_id != baseline_id and trigger != "eval":
            def set_baseline(c: Capture) -> None:
                c.baseline_capture_id = baseline_id

            capture = await self.store.update(Capture, capture.id, set_baseline) or capture
        baseline = await self.store.get(Capture, baseline_id) if baseline_id else None

        provider_name = provider_name or session.assess_provider
        assessment = Assessment(
            session_id=session.id, capture_id=capture.id, shot_id=capture.shot_id,
            setup_revision_id=capture.setup_revision_id, baseline_capture_id=baseline.id if baseline else None,
            kind="compare" if baseline else "assess", trigger=trigger,
            prompt_version=PROMPT_VERSION if self.settings.spoken_first else PROMPT_VERSION + "-spoken-last",
            provider=provider_name, model_requested=self.settings.model_for(provider_name), status="running",
            context_generation=self.tracker.get(session.id).generation,
        )
        await self.store.put(assessment)
        await self._set_state(capture.id, ProcessingState.analyzing)
        self.bus.publish("analysis.started", session_id=session.id, capture_id=capture.id,
                         assessment_id=assessment.id, trigger=trigger, kind=assessment.kind)
        t_start = time.monotonic()
        try:
            regions = shot.sharp_regions if shot else []
            root = self.session_root(session.id)
            t_ev = time.monotonic()
            ev = await ensure_evidence(capture, regions, root, self.settings, self.executor)
            assessment.timings["evidence_ms"] = (time.monotonic() - t_ev) * 1000
            if capture.evidence.get("regions_key") != ev["regions_key"]:
                # Regions changed since ingest: persist the new crops so the UI can fetch them.
                def keep(c: Capture, ev=ev) -> None:
                    c.evidence = ev

                capture = await self.store.update(Capture, capture.id, keep) or capture
            t_ev = time.monotonic()
            b_ev = await ensure_evidence(baseline, regions, root, self.settings, self.executor) if baseline else None
            if baseline:
                assessment.timings["baseline_evidence_ms"] = (time.monotonic() - t_ev) * 1000
            t_req = time.monotonic()
            assessment.measurements = ev["measurements"]
            assessment.evidence = ev["crops"] + [{"id": "overview", "path": ev["overview"]["path"]}]
            teaching = await self._teaching_requested(session, trigger)
            req, vctx = await self._build_request(session, shot, setup, capture, ev, baseline, b_ev, teaching)
            assessment.timings["build_request_ms"] = (time.monotonic() - t_req) * 1000

            provider = self.providers.get(provider_name)
            assessment.model_requested = provider.model
            if trigger != "eval":
                await self.check_budget(session, provider)
            ids = {"session_id": session.id, "capture_id": capture.id, "assessment_id": assessment.id}
            timeout = self.settings.model_timeout_s + 5
            t_wait = time.monotonic()
            async with self._sem:
                wait_ms = (time.monotonic() - t_wait) * 1000
                assessment.timings["queue_wait_ms"] = wait_ms
                await self.timer.mark("model_request_started", **ids)
                t0 = time.monotonic()
                early = self._early_speech(trigger, speak, provider, guard, session, capture, assessment, t_start)
                gen_kw = {"on_text": early.on_text} if early else {}
                resp, call = await self.recorder.call(lambda: provider.generate(req, **gen_kw), purpose="assess",
                                                      attempt=0,
                                                      provider=provider, req=req, queue_wait_ms=wait_ms,
                                                      timeout_s=timeout, collect=assessment.model_call_ids, **ids)
                assessment.timings["model_ms"] = (time.monotonic() - t0) * 1000
                await self.timer.mark("model_response_received", **ids)
                result, errors, warnings = validate_output(resp.text, vctx)
                await self.recorder.mark(call, "ok" if result else "invalid", errors, warnings)
                usage = dict(resp.usage)
                if result is None:
                    assessment.repair_attempted = True
                    self.bus.publish("analysis.repairing", session_id=session.id, capture_id=capture.id,
                                     errors=errors[:5])
                    t1 = time.monotonic()
                    resp2, call2 = await self.recorder.call(lambda: provider.repair(req, resp, errors),
                                                            purpose="assess", attempt=1, provider=provider,
                                                            req=req, request_extra={"repair_errors": errors},
                                                            timeout_s=timeout, collect=assessment.model_call_ids,
                                                            **ids)
                    assessment.timings["repair_ms"] = (time.monotonic() - t1) * 1000
                    for k, v in resp2.usage.items():
                        if isinstance(v, int | float):
                            usage[k] = (usage.get(k) or 0) + v
                    result, errors2, warnings = validate_output(resp2.text, vctx)
                    await self.recorder.mark(call2, "ok" if result else "invalid", errors2, warnings)
                    resp = resp2
                    if result is None:
                        raise ProviderError("invalid model output after one repair: " + "; ".join(errors2[:6]))
            assessment.model_resolved = resp.model_resolved
            assessment.usage = usage
            assessment.cost_estimate_usd = estimate_cost(usage, self.settings.prices.get(resp.model_resolved or "")
                                                         or self.settings.prices.get(provider.model or ""))
            assessment.result = result.model_dump()
            assessment.warnings = warnings
            assessment.exposure_note = exposure_note_for(
                assessment.result.get("primary_action"), capture.exif, self._exposure_ctx(setup, capture))
            assessment.status = "completed"
            assessment.completed_at = utcnow()
            assessment.timings["total_ms"] = (time.monotonic() - t_start) * 1000
            await self.store.put(assessment)
            await self.timer.mark("result_validated", session_id=session.id, capture_id=capture.id,
                                  assessment_id=assessment.id)
            await self._link_experiments(assessment, result, baseline)
            await self._set_state(capture.id, ProcessingState.analyzed)
            self.bus.publish("analysis.completed", session_id=session.id, capture_id=capture.id,
                             assessment_id=assessment.id, verdict=result.verdict, trigger=trigger)
            was_down = self.providers.health.get(provider_name, {}).get("ok") is False
            self.providers.health[provider_name] = {"ok": True, "at": utcnow()}
            if was_down:
                self._spawn(self.run_armed(session.id))
        except BudgetExceeded as exc:
            await self._fail(assessment, capture.id, f"Budget reached: {exc}")
            if self.on_budget_exceeded:
                await self.on_budget_exceeded(session.id, str(exc))
            return assessment
        except (ProviderUnavailable, TimeoutError) as exc:
            await self._fail(assessment, capture.id, unavailable_message(assessment.provider, exc), unavailable=True)
            return assessment
        except Exception as exc:
            log.exception("assessment failed")
            await self._fail(assessment, capture.id, str(exc))
            return assessment

        early_task = early.task if early else None
        corrected = False
        if speak and trigger != "eval" and early_task is not None:
            # spoken_text was already being spoken while the rest streamed in: finish it, then add what only the
            # validated result can say (exposure starting point, teaching prompt), or correct it after a repair.
            text = self.spoken_for(assessment)
            t_sp = time.monotonic()
            status = await early_task
            final = (assessment.result or {}).get("spoken_text", "").strip()
            meta = {"session_id": session.id, "capture_id": capture.id, "assessment_id": assessment.id,
                    "kind": "advice"}
            corrected = final != (early.text or "").strip()
            if corrected:
                self.bus.publish("coach.speech.corrected", session_id=session.id, capture_id=capture.id,
                                 assessment_id=assessment.id)
                status = await self.audio.speak(f"Correction: {text}", guard, meta)
            elif status == "spoken" and text.strip() != final:
                await self.audio.speak(text.strip()[len(final):].strip(), guard, meta)
            speech_ms = (time.monotonic() - t_sp) * 1000
            assessment.timings["spoken_early"] = 1
        elif speak and trigger != "eval":
            text = self.spoken_for(assessment)
            if trigger == "user" and not self.tracker.is_latest(session.id, capture.shot_id, capture.id):
                text = f"About earlier photo {capture.seq}: {text}"  # explicit review of an older photo
            t_sp = time.monotonic()
            status = await self.audio.speak(text, guard,
                                            {"session_id": session.id, "capture_id": capture.id,
                                             "assessment_id": assessment.id, "kind": "advice"})
            speech_ms = (time.monotonic() - t_sp) * 1000
        else:
            status = "not_applicable"

        def set_speech(a: Assessment) -> None:
            if early_task is not None:
                a.timings["spoken_early"] = 1
                a.timings["spoken_text_ready_ms"] = early.ready_ms
                a.early_speech = {"text": early.text, "ready_ms": early.ready_ms, "corrected": corrected}
            if status != "not_applicable":
                a.timings["speech_call_ms"] = speech_ms
                a.timings["spoken_words"] = len(text.split())
            a.speech_status = "spoken" if status == "spoken" else (
                "not_applicable" if status == "not_applicable" else "suppressed" if status == "suppressed" else "cancelled")

        await self.store.update(Assessment, assessment.id, set_speech)
        if status == "suppressed":
            self.bus.publish("coach.speech.suppressed", session_id=session.id, capture_id=capture.id,
                             assessment_id=assessment.id, reason="context no longer current")
        return await self.store.get(Assessment, assessment.id)

    preferences_source = None  # set by the app: async (session) -> {yours, project, template, shoot}

    async def preferences_for(self, session: Session | None) -> dict[str, str | None]:
        """Drew's taste, most general first (the prompt says the most specific wins)."""
        if self.preferences_source is not None:
            return await self.preferences_source(session)
        return {"yours": self.settings.my_preferences, "project": self.settings.project_preferences,
                "template": None, "shoot": None}

    def _early_speech(self, trigger, speak, provider, guard, session, capture, assessment, t_start):
        """Early speech for auto-coaching when the provider streams; None otherwise."""
        if not (self.settings.stream_speech and self.settings.spoken_first and speak and trigger == "auto"
                and getattr(provider, "supports_streaming", False)):
            return None
        return _EarlySpeech(self, guard, {"session_id": session.id, "capture_id": capture.id,
                                          "assessment_id": assessment.id, "kind": "advice"}, t_start)

    async def check_budget(self, session: Session, provider) -> None:
        if getattr(provider, "name", "") == "mock":
            return
        summary = usage_summary(await self.store.model_calls(session.id), session, self.settings)
        if summary["exceeded"]:
            raise BudgetExceeded(summary["reason"])

    def spoken_for(self, a: Assessment) -> str:
        r = a.result or {}
        text = r.get("spoken_text", "")
        note = a.exposure_note or {}
        if note.get("applicable") and note.get("rounded_label"):
            text += f" Starting point: {note['rounded_label']} at f/{note['new_f_number']:g}."
        elif a.exposure_note and not note.get("applicable"):
            text += " Check exposure after the change."
        if r.get("teaching_prompt"):
            text += " " + r["teaching_prompt"]
        return text

    async def _fail(self, a: Assessment, capture_id: str, error: str, unavailable: bool = False) -> None:
        a.status = "failed"
        a.error = error
        a.speech_status = "not_applicable"
        a.completed_at = utcnow()
        await self.store.put(a)
        await self._set_state(capture_id, ProcessingState.failed, error)
        if unavailable:
            self.providers.health[a.provider] = {"ok": False, "at": utcnow(), "error": error}
        self.bus.publish("analysis.failed", session_id=a.session_id, capture_id=capture_id, assessment_id=a.id,
                         error=error, ai_unavailable=unavailable, key_rejected="API key rejected" in error)

    async def _set_state(self, capture_id: str, state: ProcessingState, error: str | None = None) -> None:
        def f(c: Capture) -> None:
            c.processing_state = state
            c.error = error

        await self.store.update(Capture, capture_id, f)

    async def _teaching_requested(self, session: Session, trigger: str) -> bool:
        if not session.teaching_mode or trigger == "eval" or self.settings.teaching_prompt_every <= 0:
            return False
        done = [a for a in await self.store.assessments(session.id) if a.status == "completed" and a.trigger != "eval"]
        return (len(done) + 1) % self.settings.teaching_prompt_every == 0

    @staticmethod
    def _subject_check(ev: dict, b_ev: dict | None) -> dict[str, Any] | None:
        """On-device classifier labels and feature-print distance to the baseline (imaging/subject.py)."""
        from ..imaging.subject import featureprint_distance, load_featureprint

        labels = (ev.get("measurements") or {}).get("subject_labels")
        if labels is None:
            return None
        out: dict[str, Any] = {"labels": labels}
        if b_ev:
            out["distance_to_baseline"] = featureprint_distance(load_featureprint(ev.get("featureprint")),
                                                                load_featureprint(b_ev.get("featureprint")))
        return out

    @staticmethod
    def _exposure_ctx(setup: SetupRevision | None, capture: Capture) -> ExposureContext:
        exif = capture.exif
        mode = setup.exposure_mode if setup else "unknown"
        if exif.get("exposure_program") == "manual" or exif.get("exposure_mode_manual"):
            mode = "manual" if mode in ("unknown", "manual") else mode
        return ExposureContext(light=setup.light if setup else "unknown", exposure_mode=mode,
                               iso_mode=setup.iso_mode if setup else "unknown", flash_fired=exif.get("flash_fired"))

    async def _build_request(self, session, shot, setup, capture, ev, baseline, b_ev, teaching) -> tuple[ModelRequest, ValidationContext]:
        images = [ImageInput("current", "overview", "whole_image", "current photo, full frame (downscaled)",
                             ev["overview"]["path"])]
        crops_desc = []
        for c in ev["crops"]:
            images.append(ImageInput("current", "crop", c["id"], f"current crop '{c['label']}' "
                                     f"({'native resolution' if c['native_resolution'] else 'downscaled'})", c["path"]))
            crops_desc.append({"region_id": c["id"], "label": c["label"], "source": c["source"], "role": "current",
                               "rect_normalized": c["rect"]})
        baseline_ctx = None
        if baseline and b_ev:
            images.append(ImageInput("baseline", "overview", "baseline_whole_image",
                                     f"BASELINE photo #{baseline.seq} (previous attempt), full frame", b_ev["overview"]["path"]))
            comparability = {}
            for c in b_ev["crops"]:
                bid = f"baseline_{c['id']}"
                images.append(ImageInput("baseline", "crop", bid, f"BASELINE crop '{c['label']}'", c["path"]))
                crops_desc.append({"region_id": bid, "label": c["label"], "source": c["source"], "role": "baseline",
                                   "rect_normalized": c["rect"]})
                cur = ev["measurements"]["regions"].get(c["id"])
                prev = b_ev["measurements"]["regions"].get(c["id"])
                if cur and prev:
                    ok, reasons = region_comparable(cur, prev, capture.exif, baseline.exif)
                    comparability[c["id"]] = {"comparable": ok, "reasons": reasons}
            prev_a = await self.store.latest_completed_assessment(baseline.id)
            baseline_ctx = {
                "capture_id": baseline.id,
                "capture_seq": baseline.seq,
                "previous_verdict": (prev_a.result or {}).get("verdict") if prev_a else None,
                "previous_advice": (prev_a.result or {}).get("primary_action") if prev_a else None,
                "user_reported_change": capture.user_reported_change or "not reported",
                "metadata": metadata_for_model(baseline.exif),
                "measurements": compact_measurements(b_ev["measurements"]),
                "comparability": comparability,
                "note": "Similar composition is not proof the advice was followed.",
            }
        history = []
        if shot:
            for prev in (await self.store.captures(session.id, shot.id))[-(self.settings.history_limit + 1):]:
                if prev.id == capture.id:
                    continue
                pa = await self.store.latest_completed_assessment(prev.id)
                if pa and pa.result:
                    history.append({"capture_seq": prev.seq, "verdict": pa.result.get("verdict"),
                                    "action": (pa.result.get("primary_action") or {}).get("instruction"),
                                    "comparison": (pa.result.get("comparison") or {}).get("outcome")})
        allowed = [d["region_id"] for d in crops_desc]
        criteria = [c.model_dump() for c in shot.criteria] if shot else []
        # The JPEG arrives ~1 s before its ORF (OM Capture), so "RAW kept" also counts earlier pairs this session.
        raw_now = bool(capture.raw_path)
        raw_before = raw_now or any(c.raw_path for c in (await self.store.captures(session.id))[-10:])
        context = {
            "task": "compare" if baseline_ctx else "assess",
            "shot": {
                "title": shot.title if shot else "unassigned",
                "purpose": shot.purpose if shot else "",
                "must_show": shot.must_show if shot else [],
                "framing": shot.framing if shot else "",
                "criteria": criteria,
                "desired_sharp_regions": [r.label or r.id for r in shot.sharp_regions] if shot else [],
            },
            "setup": setup.model_dump(exclude={"id", "session_id", "created_at"}) if setup else "unknown",
            "product": session.product,
            "metadata": metadata_for_model(capture.exif),
            "measurements": compact_measurements(ev["measurements"]),
            "subject_check": self._subject_check(ev, b_ev if baseline else None),
            "supplied_crops": crops_desc,
            "allowed_region_ids": allowed + ["whole_image"],
            "history": history,
            "baseline": baseline_ctx,
            "teaching_prompt_requested": teaching,
            "frame_of_reference": FRAME_OF_REFERENCE,
            "capture_seq": capture.seq,
            "capture": {"raw_kept": raw_before,
                        "basis": "RAW paired with this photo" if raw_now else
                        "earlier photos this session had RAW" if raw_before else "no RAW seen this session"},
            "preferences": await self.preferences_for(session),
        }
        schema = provider_json_schema(AssessmentResult)
        if self.settings.spoken_first:
            req = ModelRequest("assess", SYSTEM_ASSESS + SPOKEN_FIRST_NOTE, context, images, "assessment",
                               spoken_first_schema(schema), PROMPT_VERSION)
        else:
            req = ModelRequest("assess", SYSTEM_ASSESS, context, images, "assessment", schema,
                               PROMPT_VERSION + "-spoken-last")
        vctx = ValidationContext(
            region_ids=set(allowed), criterion_ids={c["id"] for c in criteria},
            baseline_capture_id=baseline.id if baseline_ctx else None, teaching_prompt_requested=teaching,
            metadata_available=bool(capture.exif.get("metadata_available")),
            exposure_metadata_available=bool(capture.exif.get("exposure_known")),
        )
        return req, vctx

    async def _link_experiments(self, a: Assessment, result: AssessmentResult, baseline: Capture | None) -> None:
        if baseline and result.comparison:
            exp = await self.store.open_experiment_for_baseline(baseline.id)
            if exp:
                exp.follow_up_capture_id = a.capture_id
                exp.comparison_assessment_id = a.id
                exp.comparison_outcome = result.comparison.outcome
                exp.updated_at = utcnow()
                await self.store.put(exp)
                self.bus.publish("experiment.updated", session_id=a.session_id, capture_id=a.capture_id,
                                 experiment_id=exp.id)
        if result.primary_action and a.trigger != "eval":
            pa = result.primary_action
            exp = Experiment(session_id=a.session_id, shot_id=a.shot_id, baseline_capture_id=a.capture_id,
                             baseline_assessment_id=a.id, suggested_adjustment=pa.instruction,
                             held_constant=pa.hold_constant, intended_effect=pa.expected_effect)
            await self.store.put(exp)
            self.bus.publish("experiment.created", session_id=a.session_id, capture_id=a.capture_id,
                             experiment_id=exp.id)

    # --- follow-up questions -------------------------------------------------------------
    async def answer_question(self, session: Session, capture: Capture | None, question: str,
                              is_older: bool, voice_turn_id: str | None = None) -> tuple[ConversationAnswer, dict[str, Any]]:
        saved = await self.store.latest_completed_assessment(capture.id) if capture else None
        shot = await self.store.get(ShotRequirement, capture.shot_id) if capture and capture.shot_id else None
        needs_pixels = capture is not None and (saved is None or _mentions_visual(question))
        images = []
        if needs_pixels and capture and capture.evidence.get("overview"):
            images.append(ImageInput("current", "overview", "whole_image", f"photo #{capture.seq}",
                                     capture.evidence["overview"]["path"]))
        context = {
            "question": question,
            "preferences": await self.preferences_for(session),
            "is_older_photo": is_older,
            "capture_seq": capture.seq if capture else None,
            "shot": {"title": shot.title, "purpose": shot.purpose,
                     "criteria": [c.model_dump() for c in shot.criteria]} if shot else None,
            "metadata": metadata_for_model(capture.exif) if capture else None,
            "saved_assessment": saved.result if saved else None,
            "exposure_note": saved.exposure_note if saved else None,
            "measurements": compact_measurements(capture.evidence.get("measurements", {})) if capture else None,
        }
        req = ModelRequest("answer", SYSTEM_ANSWER, context, images, "answer",
                           provider_json_schema(ConversationAnswer), ANSWER_PROMPT_VERSION)
        provider = self.providers.get(session.assess_provider)
        await self.check_budget(session, provider)
        ids = {"session_id": session.id, "capture_id": capture.id if capture else None, "voice_turn_id": voice_turn_id}
        timeout = self.settings.model_timeout_s + 5
        t0 = time.monotonic()
        calls: list[str] = []
        async with self._sem:
            wait_ms = (time.monotonic() - t0) * 1000
            resp, call = await self.recorder.call(lambda: provider.generate(req), purpose="answer", attempt=0,
                                                  provider=provider, req=req, queue_wait_ms=wait_ms,
                                                  timeout_s=timeout, collect=calls, **ids)
        try:
            ans = ConversationAnswer.model_validate_json(resp.text)
            await self.recorder.mark(call, "ok")
        except Exception as exc:
            await self.recorder.mark(call, "invalid", [str(exc)[:500]])
            errs = ["output did not match the answer schema"]
            resp, call2 = await self.recorder.call(lambda: provider.repair(req, resp, errs), purpose="answer",
                                                   attempt=1, provider=provider, req=req, timeout_s=timeout,
                                                   collect=calls, **ids)
            ans = ConversationAnswer.model_validate_json(resp.text)
            await self.recorder.mark(call2, "ok")
        meta = {"model_resolved": resp.model_resolved, "usage": resp.usage, "used_pixels": bool(images),
                "latency_ms": (time.monotonic() - t0) * 1000, "queue_wait_ms": wait_ms,
                "prompt_version": ANSWER_PROMPT_VERSION, "provider": provider.name, "model_call_ids": calls}
        return ans, meta


class _EarlySpeech:
    """Starts speaking `spoken_text` the moment its closing quote streams in (once per assessment)."""

    def __init__(self, service: CoachingService, guard, meta: dict, t_start: float):
        self.service, self.guard, self.meta, self.t_start = service, guard, meta, t_start
        self.task: asyncio.Task | None = None
        self.text: str | None = None
        self.ready_ms: float | None = None

    def on_text(self, partial: str) -> None:
        if self.task is not None:
            return
        spoken = completed_string_field(partial, "spoken_text")
        if not spoken or not spoken.strip():
            return
        self.text = spoken
        self.ready_ms = round((time.monotonic() - self.t_start) * 1000, 1)
        # The verdict streams before spoken_text, so the panel can show both while the details arrive.
        self.service.bus.publish("coach.speech.early", session_id=self.meta["session_id"],
                                 capture_id=self.meta["capture_id"], ready_ms=self.ready_ms, text=spoken,
                                 verdict=completed_string_field(partial, "verdict"))
        self.task = self.service._spawn(self.service.audio.speak(spoken, self.guard, self.meta))


_VISUAL_WORDS = ("look", "see", "sharp", "focus", "blur", "glare", "shine", "reflect", "bright", "dark", "visible",
                 "frame", "crop", "color", "colour", "shadow", "background", "is the", "does the", "can you")


def _mentions_visual(q: str) -> bool:
    ql = q.lower()
    return any(w in ql for w in _VISUAL_WORDS)


def assessment_images_exist(a: Assessment) -> bool:
    return all(Path(e["path"]).exists() for e in a.evidence if "path" in e)
