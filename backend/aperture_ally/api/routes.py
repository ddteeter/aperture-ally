"""REST + WebSocket API. Loopback-only by default; origins/hosts restricted; files served by ID only."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import (
    APIRouter,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..coaching.providers.mock import MockProvider
from ..coverage import KeeperError, compute_coverage, export_coverage
from ..domain.assessment import AssessmentResult, provider_json_schema
from ..domain.exposure import ExposureContext, equivalent_exposure
from ..domain.models import (
    Assessment,
    Capture,
    Criterion,
    Experiment,
    Region,
    SessionStatus,
    SetupFields,
    ShotRequirement,
    utcnow,
)
from ..services import ApertureAllyApp, NotFound
from ..telemetry.export import export_timing
from ..telemetry.timing import summarize

router = APIRouter(prefix="/api")


def app_of(request: Request | WebSocket) -> ApertureAllyApp:
    return request.app.state.coach


# --- bodies ----------------------------------------------------------------------------------
class SessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    product: str = ""
    watch_folder: str | None = None
    template: Literal["running_shoe", "empty"] | None = "running_shoe"
    assess_provider: Literal["mock", "openai", "gemini"] | None = None
    teaching_mode: bool = True
    simulated: bool = False
    setup: SetupFields | None = None


class SessionPatch(BaseModel):
    name: str | None = None
    product: str | None = None
    watch_folder: str | None = None
    assess_provider: Literal["mock", "openai", "gemini"] | None = None
    teaching_mode: bool | None = None
    status: SessionStatus | None = None


class ShotBody(BaseModel):
    title: str | None = None
    purpose: str | None = None
    must_show: list[str] | None = None
    framing: str | None = None
    sharp_regions: list[Region] | None = None
    criteria: list[Criterion] | None = None
    reference_image: str | None = None
    needs_retake: bool | None = None
    ordinal: int | None = None


class ActiveShot(BaseModel):
    shot_id: str | None


class ImportBody(BaseModel):
    paths: list[str] = Field(default_factory=list)
    shot_id: str | None = None
    auto_coach: bool = False
    replay: str | None = Field(None, description="Run a fixtures/manifest.json scenario against this session")


class CapturePatch(BaseModel):
    shot_id: str | None = None
    extra_shot_ids: list[str] | None = None
    baseline_capture_id: str | None = None
    user_reported_change: str | None = None


class AssessBody(BaseModel):
    plain: bool = Field(False, description="Assess without a baseline comparison")
    speak: bool = True
    provider: Literal["mock", "openai", "gemini"] | None = None


class CompareBody(BaseModel):
    baseline_capture_id: str
    speak: bool = True


class KeeperBody(BaseModel):
    capture_id: str
    notes: str | None = None
    criterion_notes: dict[str, str] = Field(default_factory=dict)
    link: bool = False


class ExperimentPatch(BaseModel):
    actual_change: str | None = None
    user_rating: Literal["helpful", "neutral", "harmful"] | None = None
    criterion_improved: bool | None = None
    other_criteria_worsened: bool | None = None
    lesson: str | None = None


class VoiceBody(BaseModel):
    session_id: str | None = None
    capture_id: str | None = None
    source: str = "ui"


# --- helpers ---------------------------------------------------------------------------------
async def _session_or_404(app: ApertureAllyApp, sid: str):
    try:
        return await app.get_session(sid)
    except NotFound as e:
        raise HTTPException(404, str(e)) from e


async def _capture_or_404(app: ApertureAllyApp, cid: str) -> Capture:
    c = await app.store.get(Capture, cid)
    if c is None:
        raise HTTPException(404, f"capture {cid}")
    return c


def _capture_view(c: Capture, latest: Assessment | None) -> dict[str, Any]:
    d = c.model_dump()
    ev = d.pop("evidence", {}) or {}
    d["evidence"] = {
        "available": bool(ev),
        "width": ev.get("width"), "height": ev.get("height"),
        "crops": [{k: v for k, v in x.items() if k != "path"} for x in ev.get("crops", [])],
        "measurements": ev.get("measurements"),
    }
    d["source_names"] = [Path(p).name for p in c.source_paths]
    for k in ("jpeg_path", "raw_path"):
        d[k.replace("_path", "_name")] = Path(d[k]).name if d[k] else None
    d["latest_assessment"] = _assessment_view(latest) if latest else None
    return d


def _assessment_view(a: Assessment) -> dict[str, Any]:
    d = a.model_dump()
    d["evidence"] = [{k: v for k, v in e.items() if k != "path"} for e in a.evidence]
    return d


async def session_state(app: ApertureAllyApp, sid: str) -> dict[str, Any]:
    s = await _session_or_404(app, sid)
    shots = await app.store.shots(sid)
    caps = await app.store.captures(sid)
    assessments = await app.store.assessments(sid)
    latest: dict[str, Assessment] = {}
    for a in assessments:
        latest[a.capture_id] = a
    revs = await app.store.setup_revisions(sid)
    pending = [
        {"name": Path(r["source_path"]).name, "status": r["status"], "note": r["note"]}
        for r in await app.store.source_files(sid)
        if r["status"] in ("discovered", "stabilizing", "pending_retry", "failed")
    ]
    return {
        "session": s.model_dump(),
        "shots": [x.model_dump() for x in shots],
        "setup": revs[-1].model_dump() if revs else None,
        "setup_revisions": len(revs),
        "captures": [_capture_view(c, latest.get(c.id)) for c in caps],
        "experiments": [e.model_dump() for e in await app.store.experiments(sid)],
        "keepers": [k.model_dump() for k in await app.store.active_keepers(sid)],
        "coverage": await compute_coverage(app.store, sid, verify=False),
        "pending_files": pending,
        "voice": app.voice.snapshot(),
        "watching": app.ingest.watched_session_id == sid,
        "pending_change": app.tracker.get(sid).pending_change,
        "provider_health": app.providers.health,
        "providers_configured": app.providers.configured(),
    }


# --- sessions --------------------------------------------------------------------------------
@router.get("/health")
async def health(request: Request):
    app = app_of(request)
    return {"ok": True, "started": app.started, "time": utcnow()}


@router.get("/sessions")
async def list_sessions(request: Request):
    return [s.model_dump() for s in await app_of(request).store.list_sessions()]


@router.post("/sessions", status_code=201)
async def create_session(body: SessionCreate, request: Request):
    app = app_of(request)
    s = await app.create_session(
        name=body.name, product=body.product, watch_folder=body.watch_folder,
        template=None if body.template == "empty" else body.template, assess_provider=body.assess_provider,
        teaching_mode=body.teaching_mode, setup=body.setup.model_dump() if body.setup else None,
        simulated=body.simulated,
    )
    return s.model_dump()


@router.get("/sessions/{sid}")
async def get_session(sid: str, request: Request):
    return await session_state(app_of(request), sid)


@router.patch("/sessions/{sid}")
async def patch_session(sid: str, body: SessionPatch, request: Request):
    app = app_of(request)
    await _session_or_404(app, sid)
    try:
        s = await app.update_session(sid, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return s.model_dump()


@router.post("/sessions/{sid}/shots", status_code=201)
async def add_shot(sid: str, body: ShotBody, request: Request):
    app = app_of(request)
    await _session_or_404(app, sid)
    data = body.model_dump(exclude_unset=True)
    if not data.get("title"):
        raise HTTPException(422, "title required")
    return (await app.add_shot(sid, data)).model_dump()


@router.patch("/sessions/{sid}/shots/{shot_id}")
async def patch_shot(sid: str, shot_id: str, body: ShotBody, request: Request):
    app = app_of(request)
    shot = await app.store.get(ShotRequirement, shot_id)
    if shot is None or shot.session_id != sid:
        raise HTTPException(404, f"shot {shot_id}")
    try:
        return (await app.update_shot(shot_id, body.model_dump(exclude_unset=True, mode="json"))).model_dump()
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.patch("/sessions/{sid}/active-shot")
async def set_active_shot(sid: str, body: ActiveShot, request: Request):
    app = app_of(request)
    try:
        return (await app.set_active_shot(sid, body.shot_id)).model_dump()
    except NotFound as e:
        raise HTTPException(404, str(e)) from e


@router.patch("/sessions/{sid}/setup")
async def patch_setup(sid: str, body: dict[str, Any], request: Request):
    app = app_of(request)
    await _session_or_404(app, sid)
    unknown = set(body) - set(SetupFields.model_fields)
    if unknown:
        raise HTTPException(422, f"unknown setup fields {sorted(unknown)}")
    try:
        return (await app.update_setup(sid, body)).model_dump()
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class ChangeNote(BaseModel):
    text: str | None = Field(None, max_length=500)


@router.post("/sessions/{sid}/change-note")
async def change_note(sid: str, body: ChangeNote, request: Request):
    """'What I changed' — attached to the next capture of the active shot (used in comparison)."""
    app = app_of(request)
    await _session_or_404(app, sid)
    app.tracker.get(sid).pending_change = (body.text or "").strip() or None
    app.bus.publish("session.change_note", session_id=sid, text=body.text)
    return {"pending_change": app.tracker.get(sid).pending_change}


@router.get("/events/recent")
async def recent_events(request: Request, after_seq: int = 0):
    return [e for e in app_of(request).bus.recent if e["seq"] > after_seq]


@router.post("/sessions/{sid}/imports")
async def imports(sid: str, body: ImportBody, request: Request):
    app = app_of(request)
    await _session_or_404(app, sid)
    if body.replay:
        from ..replay import start_server_side_replay

        try:
            task_id = start_server_side_replay(request.app, sid, body.replay)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        return {"replay": body.replay, "task": task_id}
    try:
        ids = await app.ingest.import_paths(sid, [Path(p) for p in body.paths], shot_id=body.shot_id,
                                            auto_coach=body.auto_coach)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    return {"capture_ids": ids}


@router.post("/sessions/{sid}/uploads")
async def upload(sid: str, request: Request, files: list[UploadFile] = File(...),
                 shot_id: str | None = Form(None), auto_coach: bool = Form(False)):
    app = app_of(request)
    await _session_or_404(app, sid)
    paths = []
    for f in files:
        data = await f.read()
        try:
            paths.append(app.ingest.save_upload(sid, f.filename or "upload.jpg", data))
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    ids = await app.ingest.import_paths(sid, paths, origin="upload", shot_id=shot_id, auto_coach=auto_coach,
                                        extra_roots=[app.session_root(sid) / "uploads"])
    return {"capture_ids": ids}


@router.get("/sessions/{sid}/captures")
async def list_captures(sid: str, request: Request):
    app = app_of(request)
    await _session_or_404(app, sid)
    out = []
    for c in await app.store.captures(sid):
        out.append(_capture_view(c, (await app.store.assessments_for(c.id) or [None])[-1]))
    return out


@router.get("/sessions/{sid}/coverage")
async def coverage(sid: str, request: Request):
    app = app_of(request)
    await _session_or_404(app, sid)
    return await compute_coverage(app.store, sid)


@router.post("/sessions/{sid}/exports")
async def exports(sid: str, request: Request):
    app = app_of(request)
    s = await _session_or_404(app, sid)
    out = Path(s.output_folder) / "exports"
    files = await export_coverage(app.store, s, out)
    files.update(await export_timing(app.store, s, out))
    return files


# --- captures --------------------------------------------------------------------------------
@router.get("/captures/{cid}")
async def get_capture(cid: str, request: Request):
    app = app_of(request)
    c = await _capture_or_404(app, cid)
    assessments = await app.store.assessments_for(cid)
    exps = [e for e in await app.store.experiments(c.session_id)
            if cid in (e.baseline_capture_id, e.follow_up_capture_id)]
    view = _capture_view(c, assessments[-1] if assessments else None)
    view["assessments"] = [_assessment_view(a) for a in assessments]
    view["experiments"] = [e.model_dump() for e in exps]
    view["is_latest_for_shot"] = app.tracker.is_latest(c.session_id, c.shot_id, c.id)
    return view


@router.patch("/captures/{cid}")
async def patch_capture(cid: str, body: CapturePatch, request: Request):
    app = app_of(request)
    await _capture_or_404(app, cid)
    try:
        c = await app.update_capture(cid, body.model_dump(exclude_unset=True))
    except NotFound as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return _capture_view(c, None)


_IMAGE_KINDS = {"overview", "thumb", "original"}


@router.get("/captures/{cid}/image/{kind}")
async def capture_image(cid: str, kind: str, request: Request):
    app = app_of(request)
    c = await _capture_or_404(app, cid)
    ev = c.evidence or {}
    path: str | None = None
    if kind == "overview":
        path = (ev.get("overview") or {}).get("path")
    elif kind == "thumb":
        path = ev.get("thumb")
    elif kind == "original":
        path = c.jpeg_path or c.pairing.get("raw_preview_path")
    elif kind.startswith("crop_"):
        rid = kind[5:]
        path = next((x["path"] for x in ev.get("crops", []) if x["id"] == rid), None)
    if not path:
        raise HTTPException(404, "image not available")
    p = Path(path).resolve()
    if not p.is_relative_to(app.session_root(c.session_id).resolve()) or not p.exists():
        raise HTTPException(404, "image not available")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/captures/{cid}/assess", status_code=202)
async def assess(cid: str, request: Request, body: AssessBody | None = None):
    app = app_of(request)
    c = await _capture_or_404(app, cid)
    body = body or AssessBody()
    if body.provider:
        s = await app.get_session(c.session_id)
        if s.assess_provider != body.provider:
            await app.update_session(s.id, {"assess_provider": body.provider})
    app.coaching.request_review(cid, kind="assess" if body.plain else None, speak=body.speak)
    return {"queued": True, "capture_id": cid}


@router.post("/captures/{cid}/compare", status_code=202)
async def compare(cid: str, body: CompareBody, request: Request):
    app = app_of(request)
    c = await _capture_or_404(app, cid)
    b = await _capture_or_404(app, body.baseline_capture_id)
    if b.session_id != c.session_id or b.id == c.id:
        raise HTTPException(422, "baseline must be another capture in the same session")
    app.coaching.request_review(cid, baseline_capture_id=b.id, speak=body.speak)
    return {"queued": True, "capture_id": cid, "baseline_capture_id": b.id}


@router.get("/assessments/{aid}")
async def get_assessment(aid: str, request: Request):
    a = await app_of(request).store.get(Assessment, aid)
    if a is None:
        raise HTTPException(404, f"assessment {aid}")
    return _assessment_view(a)


# --- keepers / experiments -------------------------------------------------------------------
@router.post("/shots/{shot_id}/keeper", status_code=201)
async def accept_keeper(shot_id: str, body: KeeperBody, request: Request):
    app = app_of(request)
    try:
        d = await app.keepers.accept(shot_id, body.capture_id, notes=body.notes, criterion_notes=body.criterion_notes,
                                     link=body.link)
    except KeeperError as e:
        raise HTTPException(e.status, str(e)) from e
    return d.model_dump()


@router.delete("/shots/{shot_id}/keeper")
async def revoke_keeper(shot_id: str, request: Request):
    d = await app_of(request).keepers.revoke(shot_id)
    return {"revoked": d.model_dump() if d else None}


@router.patch("/experiments/{eid}")
async def patch_experiment(eid: str, body: ExperimentPatch, request: Request):
    app = app_of(request)
    patch = body.model_dump(exclude_unset=True)

    def apply(e: Experiment) -> None:
        for k, v in patch.items():
            setattr(e, k, v)

    e = await app.store.update(Experiment, eid, apply)
    if e is None:
        raise HTTPException(404, f"experiment {eid}")
    app.bus.publish("experiment.updated", session_id=e.session_id, experiment_id=eid)
    return e.model_dump()


# --- voice / speech --------------------------------------------------------------------------
async def _voice_session(app: ApertureAllyApp, body: VoiceBody) -> str | None:
    if body.session_id:
        return body.session_id
    s = await app.active_session()
    return s.id if s else None


@router.post("/voice/start")
async def voice_start(request: Request, body: VoiceBody | None = None):
    app = app_of(request)
    body = body or VoiceBody()
    return await app.voice.press(await _voice_session(app, body), capture_id=body.capture_id, source=body.source)


@router.post("/voice/stop")
async def voice_stop(request: Request, body: VoiceBody | None = None):
    return await app_of(request).voice.release(source=(body or VoiceBody()).source)


@router.post("/voice/toggle")
async def voice_toggle(request: Request, body: VoiceBody | None = None):
    app = app_of(request)
    body = body or VoiceBody()
    return await app.voice.toggle(await _voice_session(app, body), capture_id=body.capture_id, source=body.source)


@router.post("/voice/cancel")
async def voice_cancel(request: Request):
    return await app_of(request).voice.cancel("user")


@router.get("/voice")
async def voice_state(request: Request):
    return app_of(request).voice.snapshot()


@router.post("/coach/repeat")
async def coach_repeat(request: Request):
    app = app_of(request)
    last = app.audio.last_spoken
    if last is None:
        raise HTTPException(404, "nothing spoken yet")
    s = await app.active_session()
    guard = app.tracker.voice_guard(s.id) if s else (lambda: True)
    app.coaching._spawn(app.audio.speak(last.text, guard, {**last.meta, "kind": "repeat"}))
    return {"repeating": last.text}


@router.post("/coach/stop")
async def coach_stop(request: Request):
    return {"stopped": await app_of(request).audio.stop("user")}


# --- diagnostics -----------------------------------------------------------------------------
@router.get("/diagnostics")
async def diagnostics(request: Request, session_id: str | None = None):
    from ..doctor import run_checks

    app = app_of(request)
    checks = await asyncio.get_running_loop().run_in_executor(None, lambda: run_checks(app.settings, quick=True))
    marks = await app.store.timing_marks(session_id)
    stops = app.audio.stop_latencies_ms
    return {
        "checks": checks,
        "config": app.settings.public_view(),
        "keys": app.keys.diagnostics() if app.keys else {"running": False, "error": "global keys disabled (APERTURE_ALLY_GLOBAL_KEYS=none)"},
        "voice": app.voice.snapshot(),
        "speech_backend": app.speech.name,
        "speech_stop_latency_ms": {"n": len(stops), "last": stops[-5:], "max": max(stops) if stops else None},
        "providers": {"configured": app.providers.configured(), "health": app.providers.health},
        "timing": summarize(marks),
        "recent_events": list(app.bus.recent)[-80:],
        "watching": app.ingest.watched_session_id,
    }


@router.get("/diagnostics/timing")
async def timing(request: Request, session_id: str | None = None):
    return summarize(await app_of(request).store.timing_marks(session_id))


@router.post("/diagnostics/keys/learn")
async def keys_learn(request: Request):
    app = app_of(request)
    if not app.keys:
        raise HTTPException(409, "global key listener not running")
    app.keys.learn()
    return {"learning": True}


class MockTranscript(BaseModel):
    text: str


@router.post("/diagnostics/mock-transcript")
async def mock_transcript(body: MockTranscript, request: Request):
    app = app_of(request)
    t = app.voice.transcriber
    if t.name != "mock":
        raise HTTPException(409, "transcriber is not the mock")
    t.queue.append(body.text)  # type: ignore[attr-defined]
    return {"queued": len(t.queue)}  # type: ignore[attr-defined]


class MockMode(BaseModel):
    fail_mode: Literal["none", "invalid_once", "invalid_always", "unavailable", "slow"] = "none"
    latency_s: float | None = None


@router.post("/diagnostics/mock-provider")
async def mock_provider(body: MockMode, request: Request):
    p = app_of(request).providers.get("mock")
    assert isinstance(p, MockProvider)
    p.fail_mode = body.fail_mode
    p._invalid_sent = False
    if body.latency_s is not None:
        p.latency_s = body.latency_s
    return {"fail_mode": p.fail_mode, "latency_s": p.latency_s}


@router.get("/exposure/equivalent")
async def exposure(old_s: float, old_f: float, old_iso: float, new_f: float | None = None,
                   new_iso: float | None = None, light: str = "continuous", exposure_mode: str = "manual",
                   iso_mode: str = "manual", flash_fired: bool = False):
    return equivalent_exposure(old_s, old_f, old_iso, new_f, new_iso,
                               ExposureContext(light=light, exposure_mode=exposure_mode, iso_mode=iso_mode,
                                               flash_fired=flash_fired)).model_dump()


@router.get("/schema/assessment")
async def assessment_schema():
    return provider_json_schema(AssessmentResult)


# --- events ----------------------------------------------------------------------------------
@router.websocket("/events")
async def events(ws: WebSocket):
    app = app_of(ws)
    origin = ws.headers.get("origin")
    if origin and origin not in app.settings.allowed_origins:
        await ws.close(code=4403)
        return
    await ws.accept()
    q = app.bus.subscribe()
    try:
        await ws.send_text(json.dumps({"type": "hello", "seq": 0, "ts": utcnow(), "payload": {"t": time.time()}}))
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), 20)
                await ws.send_text(json.dumps(ev, default=str))
            except TimeoutError:
                await ws.send_text(json.dumps({"type": "ping", "ts": utcnow()}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        app.bus.unsubscribe(q)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFound)
    async def _nf(_request: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

