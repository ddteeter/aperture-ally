"""Coaching orchestration: evidence → model → validation → experiment linkage → guarded speech.

Scheduling policy
* Every capture is ingested and kept. Automatic coaching targets the newest ready capture of the
  active shot. At most one automatic request is *queued* per session (newer replaces older); running
  requests finish and are stored for history, but their speech is suppressed if no longer current.
* Explicit user reviews are never coalesced.
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
from .prompt import (
    ANSWER_PROMPT_VERSION,
    PROMPT_VERSION,
    SYSTEM_ANSWER,
    SYSTEM_ASSESS,
    ImageInput,
    ModelRequest,
    compact_measurements,
    metadata_for_model,
)
from .providers.base import Provider, ProviderError, ProviderUnavailable, estimate_cost

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
                raise ProviderUnavailable("OpenAI not configured: set OPENAI_API_KEY and PHOTO_COACH_OPENAI_MODEL")
            from .providers.openai_adapter import OpenAIProvider

            p = OpenAIProvider(s.openai_api_key.get_secret_value(), s.openai_model,
                               image_detail=s.openai_image_detail, timeout_s=s.model_timeout_s)
        elif name == "gemini":
            if not s.gemini_api_key or not s.gemini_model:
                raise ProviderUnavailable("Gemini not configured: set GEMINI_API_KEY and PHOTO_COACH_GEMINI_MODEL")
            from .providers.gemini_adapter import GeminiProvider

            p = GeminiProvider(s.gemini_api_key.get_secret_value(), s.gemini_model,
                               media_resolution=s.gemini_media_resolution, timeout_s=s.model_timeout_s)
        else:
            raise ProviderUnavailable(f"unknown provider {name}")
        self._cache[name] = p
        return p

    def configured(self) -> dict[str, bool]:
        s = self.settings
        return {"mock": True, "openai": bool(s.openai_api_key and s.openai_model),
                "gemini": bool(s.gemini_api_key and s.gemini_model)}


class CoachingService:
    def __init__(self, *, store, bus: EventBus, timer: Timer, settings: Settings, tracker: ContextTracker,
                 executor: Executor, providers: ProviderRegistry, audio, session_root):
        self.store = store
        self.bus = bus
        self.timer = timer
        self.settings = settings
        self.tracker = tracker
        self.executor = executor
        self.providers = providers
        self.audio = audio
        self.session_root = session_root
        self._sem = asyncio.Semaphore(settings.max_model_concurrency)
        self._pending_auto: dict[str, str] = {}
        self._running_auto: dict[str, set[asyncio.Task]] = {}
        self._inflight: dict[str, asyncio.Task] = {}  # capture_id -> latest assessment task
        self.tasks: set[asyncio.Task] = set()

    # --- scheduling ----------------------------------------------------------------------
    async def on_capture_ready(self, capture: Capture, auto: bool) -> None:
        await self.audio.invalidate()  # a new photo makes older automatic advice obsolete
        if not auto or not self.settings.auto_coach or capture.recovered:
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
        return task

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
            kind="compare" if baseline else "assess", trigger=trigger, prompt_version=PROMPT_VERSION,
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
            ev = await ensure_evidence(capture, regions, root, self.settings, self.executor)
            if capture.evidence.get("regions_key") != ev["regions_key"]:
                # Regions changed since ingest: persist the new crops so the UI can fetch them.
                def keep(c: Capture, ev=ev) -> None:
                    c.evidence = ev

                capture = await self.store.update(Capture, capture.id, keep) or capture
            b_ev = await ensure_evidence(baseline, regions, root, self.settings, self.executor) if baseline else None
            assessment.measurements = ev["measurements"]
            assessment.evidence = ev["crops"] + [{"id": "overview", "path": ev["overview"]["path"]}]
            teaching = await self._teaching_requested(session, trigger)
            req, vctx = await self._build_request(session, shot, setup, capture, ev, baseline, b_ev, teaching)

            provider = self.providers.get(provider_name)
            assessment.model_requested = provider.model
            async with self._sem:
                await self.timer.mark("model_request_started", session_id=session.id, capture_id=capture.id,
                                      assessment_id=assessment.id)
                t0 = time.monotonic()
                resp = await asyncio.wait_for(provider.generate(req), self.settings.model_timeout_s + 5)
                assessment.timings["model_ms"] = (time.monotonic() - t0) * 1000
                await self.timer.mark("model_response_received", session_id=session.id, capture_id=capture.id,
                                      assessment_id=assessment.id)
                result, errors, warnings = validate_output(resp.text, vctx)
                usage = dict(resp.usage)
                if result is None:
                    assessment.repair_attempted = True
                    self.bus.publish("analysis.repairing", session_id=session.id, capture_id=capture.id,
                                     errors=errors[:5])
                    t1 = time.monotonic()
                    resp2 = await asyncio.wait_for(provider.repair(req, resp, errors), self.settings.model_timeout_s + 5)
                    assessment.timings["repair_ms"] = (time.monotonic() - t1) * 1000
                    for k, v in resp2.usage.items():
                        if isinstance(v, int | float):
                            usage[k] = (usage.get(k) or 0) + v
                    result, errors2, warnings = validate_output(resp2.text, vctx)
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
            self.providers.health[provider_name] = {"ok": True, "at": utcnow()}
        except (ProviderUnavailable, TimeoutError) as exc:
            await self._fail(assessment, capture.id, f"AI unavailable: {exc}", unavailable=True)
            return assessment
        except Exception as exc:
            log.exception("assessment failed")
            await self._fail(assessment, capture.id, str(exc))
            return assessment

        if speak and trigger != "eval":
            text = self.spoken_for(assessment)
            if trigger == "user" and not self.tracker.is_latest(session.id, capture.shot_id, capture.id):
                text = f"About earlier photo {capture.seq}: {text}"  # explicit review of an older photo
            status = await self.audio.speak(text, guard,
                                            {"session_id": session.id, "capture_id": capture.id,
                                             "assessment_id": assessment.id, "kind": "advice"})
        else:
            status = "not_applicable"

        def set_speech(a: Assessment) -> None:
            a.speech_status = "spoken" if status == "spoken" else (
                "not_applicable" if status == "not_applicable" else "suppressed" if status == "suppressed" else "cancelled")

        await self.store.update(Assessment, assessment.id, set_speech)
        if status == "suppressed":
            self.bus.publish("coach.speech.suppressed", session_id=session.id, capture_id=capture.id,
                             assessment_id=assessment.id, reason="context no longer current")
        return await self.store.get(Assessment, assessment.id)

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
                         error=error, ai_unavailable=unavailable)

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
            "supplied_crops": crops_desc,
            "allowed_region_ids": allowed + ["whole_image"],
            "history": history,
            "baseline": baseline_ctx,
            "teaching_prompt_requested": teaching,
            "frame_of_reference": FRAME_OF_REFERENCE,
            "capture_seq": capture.seq,
        }
        req = ModelRequest("assess", SYSTEM_ASSESS, context, images, "assessment", provider_json_schema(AssessmentResult))
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
                              is_older: bool) -> tuple[ConversationAnswer, dict[str, Any]]:
        saved = await self.store.latest_completed_assessment(capture.id) if capture else None
        shot = await self.store.get(ShotRequirement, capture.shot_id) if capture and capture.shot_id else None
        needs_pixels = capture is not None and (saved is None or _mentions_visual(question))
        images = []
        if needs_pixels and capture and capture.evidence.get("overview"):
            images.append(ImageInput("current", "overview", "whole_image", f"photo #{capture.seq}",
                                     capture.evidence["overview"]["path"]))
        context = {
            "question": question,
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
        t0 = time.monotonic()
        async with self._sem:
            resp = await asyncio.wait_for(provider.generate(req), self.settings.model_timeout_s + 5)
        try:
            ans = ConversationAnswer.model_validate_json(resp.text)
        except Exception:
            resp = await provider.repair(req, resp, ["output did not match the answer schema"])
            ans = ConversationAnswer.model_validate_json(resp.text)
        meta = {"model_resolved": resp.model_resolved, "usage": resp.usage, "used_pixels": bool(images),
                "latency_ms": (time.monotonic() - t0) * 1000, "prompt_version": ANSWER_PROMPT_VERSION}
        return ans, meta


_VISUAL_WORDS = ("look", "see", "sharp", "focus", "blur", "glare", "shine", "reflect", "bright", "dark", "visible",
                 "frame", "crop", "color", "colour", "shadow", "background", "is the", "does the", "can you")


def _mentions_visual(q: str) -> bool:
    ql = q.lower()
    return any(w in ql for w in _VISUAL_WORDS)


def assessment_images_exist(a: Assessment) -> bool:
    return all(Path(e["path"]).exists() for e in a.evidence if "path" in e)
