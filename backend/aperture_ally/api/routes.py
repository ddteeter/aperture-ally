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
from pydantic import BaseModel, ConfigDict, Field

from ..coaching.providers.mock import MockProvider
from ..comparison import attribution_hint, baseline_candidates, comparison_metrics, region_labels
from ..coverage import KeeperError, compute_coverage, export_coverage
from ..domain.assessment import AssessmentResult, provider_json_schema
from ..domain.exposure import ExposureContext, equivalent_exposure
from ..domain.models import (
    Assessment,
    Capture,
    Criterion,
    Experiment,
    Region,
    Session,
    SessionStatus,
    SetupFields,
    ShotRequirement,
    utcnow,
)
from ..imaging.evidence import ZONES, ensure_zone_mask
from ..imaging.interpret import compare as compare_tonality
from ..imaging.interpret import interpret
from ..services import ApertureAllyApp, NotFound
from ..telemetry.export import export_telemetry, export_timing
from ..telemetry.timing import summarize

router = APIRouter(prefix="/api")


def app_of(request: Request | WebSocket) -> ApertureAllyApp:
    return request.app.state.coach


# --- bodies ----------------------------------------------------------------------------------
class SessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    product: str = ""
    watch_folder: str | None = None
    template: Literal["running_shoe", "running_apparel", "empty"] | None = "running_shoe"
    assess_provider: Literal["mock", "openai", "gemini", "claude"] | None = None
    teaching_mode: bool = True
    simulated: bool = False
    ui_theme: Literal["studio", "daylight"] = "studio"
    setup: SetupFields | None = None
    template_id: str | None = Field(None, description="Shoot template to copy the shot list from (wins over template)")
    project_id: str | None = None
    shoot_preferences: str = Field("", max_length=2000)


class SessionPatch(BaseModel):
    name: str | None = None
    product: str | None = None
    watch_folder: str | None = None
    assess_provider: Literal["mock", "openai", "gemini", "claude"] | None = None
    teaching_mode: bool | None = None
    status: SessionStatus | None = None
    coaching_paused: bool | None = None
    budget_usd: float | None = Field(None, ge=0)
    max_model_calls: int | None = Field(None, ge=0)
    ui_theme: Literal["studio", "daylight"] | None = None
    shoot_preferences: str | None = Field(None, max_length=2000)


class ProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, max_length=120)
    preferences: str | None = Field(None, max_length=2000)
    archived: bool | None = None


class TemplateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, max_length=120)
    preferences: str | None = Field(None, max_length=2000)
    archived: bool | None = None
    copy_from: str | None = Field(None, description="Create only: start from this template's shot list")
    shots: list[dict[str, Any]] | None = Field(None, description="Edit only: the whole shot list (a new version)")


class SaveToTemplateBody(BaseModel):
    new_name: str | None = Field(None, max_length=120, description="Save as a new template instead of updating")
    project_id: str | None = Field(None, description="With new_name: the project to put it in (default: the shoot's)")


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
    provider: Literal["mock", "openai", "gemini", "claude"] | None = None


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


class VoiceText(VoiceBody):
    text: str = Field(min_length=1, max_length=1000)


class RetryBody(BaseModel):
    when: Literal["now", "online"] = "now"


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


_region_labels = region_labels


def _capture_view(c: Capture, latest: Assessment | None) -> dict[str, Any]:
    d = c.model_dump()
    d["exif_raw_tag_count"] = len(d.pop("exif_raw", {}) or {})
    ev = d.pop("evidence", {}) or {}
    d["evidence"] = {
        "available": bool(ev),
        "width": ev.get("width"), "height": ev.get("height"),
        "crops": [{k: v for k, v in x.items() if k != "path"} for x in ev.get("crops", [])],
        "measurements": ev.get("measurements"),
        "has_clip_overlay": bool(ev.get("clip_overlay")),
        "has_zone_masks": bool(ev.get("clip_overlay")),  # zone_* masks are generated next to it on request
    }
    if ev.get("measurements"):
        d["histogram_insights"] = interpret(ev["measurements"], _region_labels(ev))
    d["source_names"] = [Path(p).name for p in c.source_paths]
    for k in ("jpeg_path", "raw_path"):
        d[k.replace("_path", "_name")] = Path(d[k]).name if d[k] else None
    d["latest_assessment"] = _assessment_view(latest) if latest else None
    return d


def _assessment_view(a: Assessment) -> dict[str, Any]:
    d = a.model_dump()
    d["evidence"] = [{k: v for k, v in e.items() if k != "path"} for e in a.evidence]
    return d


def _with_comparisons(view: dict[str, Any], c: Capture, base: Capture | None, caps: list[Capture],
                      shots: dict[str, ShotRequirement]) -> dict[str, Any]:
    """Baseline comparison (sentences + measured numbers) and the attribution hint for one capture view."""
    if base and base.evidence.get("measurements") and c.evidence.get("measurements"):
        view["histogram_changes"] = {"baseline_seq": base.seq, "changes": compare_tonality(
            base.evidence["measurements"], c.evidence["measurements"], _region_labels(c.evidence))}
    view["comparison_metrics"] = comparison_metrics(c, base)
    view["attribution_hint"] = attribution_hint(c, caps, shots)
    return view


async def _capture_views(caps: list[Capture], latest: dict[str, Assessment],
                         shots: list[ShotRequirement], only: Capture | None = None) -> list[dict[str, Any]]:
    """Capture views with comparisons; built off the event loop (framing reads overview images)."""
    by_id = {c.id: c for c in caps}
    shot_map = {s.id: s for s in shots}
    targets = [only] if only else caps

    def build() -> list[dict[str, Any]]:
        return [_with_comparisons(_capture_view(c, latest.get(c.id)), c, by_id.get(c.baseline_capture_id or ""),
                                  caps, shot_map) for c in targets]

    return await asyncio.get_running_loop().run_in_executor(None, build)


def _last_file_at(session_watch_folder: str | None, rows: list[dict]) -> str | None:
    """Newest first-detection time of a file from the watch folder."""
    if not session_watch_folder:
        return None
    root = str(Path(session_watch_folder).expanduser())
    times = [r["first_seen_at"] for r in rows
             if r["source_path"] == root or r["source_path"].startswith(root.rstrip("/") + "/")]
    return max(times) if times else None


async def session_state(app: ApertureAllyApp, sid: str) -> dict[str, Any]:
    s = await _session_or_404(app, sid)
    shots = await app.store.shots(sid)
    caps = await app.store.captures(sid)
    assessments = await app.store.assessments(sid)
    latest: dict[str, Assessment] = {}
    for a in assessments:
        latest[a.capture_id] = a
    revs = await app.store.setup_revisions(sid)
    rows = await app.store.source_files(sid)
    pending = [
        {"key": str(r["id"]), "name": Path(r["source_path"]).name, "status": r["status"], "note": r["note"]}
        for r in rows
        if r["status"] in ("discovered", "stabilizing", "pending_retry", "failed")
    ]
    return {
        "session": s.model_dump(),
        "shots": [x.model_dump() for x in shots],
        "setup": revs[-1].model_dump() if revs else None,
        "setup_revisions": len(revs),
        "captures": await _capture_views(caps, latest, shots),
        "experiments": [e.model_dump() for e in await app.store.experiments(sid)],
        "keepers": [k.model_dump() for k in await app.store.active_keepers(sid)],
        "coverage": await compute_coverage(app.store, sid, verify=False),
        "pending_files": pending,
        "last_file_at": _last_file_at(s.watch_folder, rows),
        "voice": app.voice.snapshot(),
        "watching": app.ingest.watched_session_id == sid,
        "pending_change": app.tracker.get(sid).pending_change,
        "origin": await app.projects.shoot_origin(s),
        "usage": await app.usage(sid),
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
    store = app_of(request).store
    counts = await store.session_counts()
    zero = {"shot_count": 0, "capture_count": 0, "keeper_count": 0, "cover_capture_id": None}
    projects = app_of(request).projects
    out = []
    for s in await store.list_sessions():
        o = await projects.shoot_origin(s)
        origin = {k: o[k] for k in ("project_name", "template_name", "template_current_version", "saved")}
        out.append({**s.model_dump(), **zero, **counts.get(s.id, {}), "origin": {**origin, "changes": len(o["changes"])}})
    return out


@router.post("/sessions", status_code=201)
async def create_session(body: SessionCreate, request: Request):
    app = app_of(request)
    s = await app.create_session(
        name=body.name, product=body.product, watch_folder=body.watch_folder,
        template=None if body.template == "empty" else body.template, assess_provider=body.assess_provider,
        teaching_mode=body.teaching_mode, setup=body.setup.model_dump() if body.setup else None,
        simulated=body.simulated, ui_theme=body.ui_theme, template_id=body.template_id,
        project_id=body.project_id, shoot_preferences=body.shoot_preferences,
    )
    return s.model_dump()


@router.get("/assessments/{aid}/calls")
async def assessment_calls(aid: str, request: Request):
    """What the coach saw: every stored model call (request + raw response) behind one assessment."""
    app = app_of(request)
    if await app.store.get(Assessment, aid) is None:
        raise HTTPException(404, "assessment not found")
    out = []
    for c in await app.store.assessment_calls(aid):
        d = c.model_dump(exclude={"network", "response_id"})
        req = dict(d.get("request") or {})
        # Paths stay on this computer; the UI shows images through the capture image endpoints instead.
        req["images"] = [{k: v for k, v in im.items() if k != "path"} for im in req.get("images") or []]
        d["request"] = req
        out.append(d)
    return out


# --- projects and shoot templates -------------------------------------------------------------
def _project_errors(fn):
    from functools import wraps

    from ..projects import NotFoundError

    @wraps(fn)
    async def wrapped(*a, **kw):
        try:
            return await fn(*a, **kw)
        except NotFoundError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    return wrapped


@router.get("/projects")
async def list_projects(request: Request):
    return await app_of(request).projects.overview()


@router.post("/projects", status_code=201)
@_project_errors
async def create_project(body: ProjectBody, request: Request):
    return (await app_of(request).projects.create_project(body.name or "", body.preferences or "")).model_dump()


@router.patch("/projects/{pid}")
@_project_errors
async def patch_project(pid: str, body: ProjectBody, request: Request):
    return (await app_of(request).projects.update_project(pid, body.model_dump(exclude_none=True))).model_dump()


@router.post("/projects/{pid}/templates", status_code=201)
@_project_errors
async def create_template(pid: str, body: TemplateBody, request: Request):
    t = await app_of(request).projects.create_template(pid, body.name or "", preferences=body.preferences or "",
                                                       copy_from=body.copy_from)
    return t.model_dump()


@router.get("/templates/{tid}")
@_project_errors
async def get_template(tid: str, request: Request):
    return (await app_of(request).projects.template(tid)).model_dump()


@router.patch("/templates/{tid}")
@_project_errors
async def patch_template(tid: str, body: TemplateBody, request: Request):
    patch = body.model_dump(exclude_none=True, exclude={"copy_from"})
    return (await app_of(request).projects.update_template(tid, patch)).model_dump()


@router.post("/sessions/{sid}/save-to-template")
@_project_errors
async def save_to_template(sid: str, body: SaveToTemplateBody, request: Request):
    app = app_of(request)
    s = await _session_or_404(app, sid)
    return (await app.projects.save_session_to_template(s, new_name=body.new_name,
                                                        project_id=body.project_id)).model_dump()


@router.get("/sessions/{sid}")
async def get_session(sid: str, request: Request):
    return await session_state(app_of(request), sid)


@router.patch("/sessions/{sid}")
async def patch_session(sid: str, body: SessionPatch, request: Request):
    app = app_of(request)
    await _session_or_404(app, sid)
    patch = body.model_dump(exclude_unset=True)
    paused = patch.pop("coaching_paused", None)
    try:
        s = await app.update_session(sid, patch) if patch else await app.get_session(sid)
        if paused is not None:
            s = await app.set_coaching_paused(sid, paused, reason="paused in the app")
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
    return {"pending_change": await app.set_change_note(sid, body.text)}


@router.get("/events/recent")
async def recent_events(request: Request, after_seq: int = 0):
    return [e for e in app_of(request).bus.recent if e["seq"] > after_seq]


@router.post("/sessions/{sid}/imports")
async def imports(sid: str, body: ImportBody, request: Request):
    app = app_of(request)
    s = await _session_or_404(app, sid)
    if body.replay:
        from ..replay import start_server_side_replay

        try:
            task_id = start_server_side_replay(request.app, sid, body.replay)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        if not s.simulated:  # replayed photos are never hardware evidence
            def simulated(x: Session) -> None:
                x.simulated = True

            await app.store.update(Session, sid, simulated)
            app.bus.publish("session.updated", session_id=sid, simulated=True)
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
    await app.telemetry.flush()
    files.update(await export_telemetry(app.store, s, out / "telemetry"))
    return files


@router.get("/sessions/{sid}/setup-revisions")
async def setup_revisions(sid: str, request: Request):
    app = app_of(request)
    await _session_or_404(app, sid)
    caps = await app.store.captures(sid)
    out = []
    for rev in await app.store.setup_revisions(sid):
        seqs = [c.seq for c in caps if c.setup_revision_id == rev.id]
        out.append({**rev.model_dump(), "capture_count": len(seqs), "first_seq": min(seqs) if seqs else None,
                    "last_seq": max(seqs) if seqs else None})
    return out


@router.post("/sessions/{sid}/pending-files/{key}/retry")
async def pending_retry(sid: str, key: str, request: Request):
    """Read a stuck watch-folder file again now (clears the retry backoff)."""
    app = app_of(request)
    s = await _session_or_404(app, sid)
    try:
        row = await app.ingest.retry_source(s, key)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(409, str(e)) from e
    if row is None:
        raise HTTPException(404, f"pending file {key}")
    return {"ok": True}


@router.post("/sessions/{sid}/pending-files/{key}/skip")
async def pending_skip(sid: str, key: str, request: Request):
    """Stop trying to read a file; it is recorded as skipped and not retried."""
    app = app_of(request)
    await _session_or_404(app, sid)
    try:
        row = await app.ingest.skip_source(sid, key)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    if row is None:
        raise HTTPException(404, f"pending file {key}")
    return {"ok": True}


# --- captures --------------------------------------------------------------------------------
@router.get("/captures/{cid}")
async def get_capture(cid: str, request: Request):
    app = app_of(request)
    c = await _capture_or_404(app, cid)
    assessments = await app.store.assessments_for(cid)
    exps = [e for e in await app.store.experiments(c.session_id)
            if cid in (e.baseline_capture_id, e.follow_up_capture_id)]
    caps = await app.store.captures(c.session_id)
    latest = {cid: assessments[-1]} if assessments else {}
    (view,) = await _capture_views(caps, latest, await app.store.shots(c.session_id), only=c)
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
    elif kind == "clip_overlay":
        if ev.get("clip_overlay") and ev.get("image_path") and Path(ev["image_path"]).exists():
            from ..imaging.evidence import ensure_clip_overlay

            out = Path(ev["clip_overlay"])
            if out.resolve().is_relative_to(app.session_root(c.session_id).resolve()):
                await asyncio.get_running_loop().run_in_executor(
                    app.executor, lambda: ensure_clip_overlay(Path(ev["image_path"]), ev["overview"], out))
                path = str(out)
    elif kind.startswith("zone_") and kind[5:] in ZONES:
        if ev.get("clip_overlay") and ev.get("image_path") and Path(ev["image_path"]).exists():
            overlay = Path(ev["clip_overlay"])
            if overlay.resolve().is_relative_to(app.session_root(c.session_id).resolve()):
                out = await asyncio.get_running_loop().run_in_executor(
                    app.executor, lambda: ensure_zone_mask(Path(ev["image_path"]), ev["overview"], overlay, kind[5:]))
                path = str(out)
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
    media = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(p, media_type=media, headers={"Cache-Control": "private, max-age=3600"})


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


@router.post("/captures/{cid}/cancel")
async def cancel_analysis(cid: str, request: Request):
    """Cancel queued/running analysis of this capture; a late result is dropped and never spoken."""
    app = app_of(request)
    await _capture_or_404(app, cid)
    return {"cancelled": await app.coaching.cancel(cid)}


@router.post("/captures/{cid}/retry", status_code=202)
async def retry_analysis(cid: str, request: Request, body: RetryBody | None = None):
    """now: run the assessment again. online: run it once, automatically, when the provider is reachable."""
    app = app_of(request)
    await _capture_or_404(app, cid)
    body = body or RetryBody()
    if body.when == "online":
        await app.coaching.arm_retry_online(cid)
        return {"queued": False, "armed": True, "capture_id": cid}

    def disarm(c: Capture) -> None:
        c.retry_when_online = False

    await app.store.update(Capture, cid, disarm)
    app.coaching.request_review(cid)
    return {"queued": True, "armed": False, "capture_id": cid}


@router.post("/captures/{cid}/reread")
async def reread_capture(cid: str, request: Request):
    """Decode a capture's file again after a failed read and rebuild its evidence."""
    app = app_of(request)
    c = await _capture_or_404(app, cid)
    if c.processing_state != "failed" or c.evidence.get("measurements"):
        raise HTTPException(409, "only a photo whose file could not be read can be re-read")
    ok, error = await app.ingest.reread_capture(c)
    return {"ok": ok, "error": error}


@router.get("/captures/{cid}/baseline-candidates")
async def baseline_candidates_route(cid: str, request: Request):
    app = app_of(request)
    c = await _capture_or_404(app, cid)
    caps = await app.store.captures(c.session_id, c.shot_id) if c.shot_id else []
    verdicts: dict[str, str | None] = {}
    for x in caps:
        if x.seq < c.seq:
            a = await app.store.latest_completed_assessment(x.id)
            verdicts[x.id] = (a.result or {}).get("verdict") if a else None
    return await asyncio.get_running_loop().run_in_executor(None, lambda: baseline_candidates(c, caps, verdicts))


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


@router.post("/voice/text")
async def voice_text(body: VoiceText, request: Request):
    """A typed utterance through the voice pipeline: commands, or a question answered by the coach."""
    app = app_of(request)
    if body.capture_id:
        await _capture_or_404(app, body.capture_id)
    res = await app.voice.text(await _voice_session(app, body), body.text, capture_id=body.capture_id,
                               source=body.source)
    if res.get("voice_turn_id") is None:
        raise HTTPException(409, res.get("error") or "no active session")
    return res


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


# --- audio preferences (speech speed, received sound, cue volume) ------------------------------
PREVIEW_TEXT = "Needs retake. The toe is clipping to pure white on the left side, so lower the exposure by one stop."


def _prefs_view(app) -> dict[str, Any]:
    from ..prefs import CUE_VOLUME_MAX, CUE_VOLUME_MIN, SPEECH_RATE_MAX, SPEECH_RATE_MIN, system_sounds

    return {"prefs": app.prefs.current.model_dump(), "defaults": app.prefs.defaults.model_dump(),
            "sounds": system_sounds(), "speech_rate_range": [SPEECH_RATE_MIN, SPEECH_RATE_MAX],
            "cue_volume_range": [CUE_VOLUME_MIN, CUE_VOLUME_MAX], "received_cue": app.settings.received_cue,
            "speech_backend": app.speech.name}


@router.get("/prefs")
async def get_prefs(request: Request):
    return _prefs_view(app_of(request))


class PrefsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speech_rate_wpm: int | None = None
    received_sound: str | None = None
    cue_volume: float | None = None
    my_preferences: str | None = None


class PreviewBody(BaseModel):
    what: Literal["speech", "received", "mix"] = "speech"


@router.patch("/prefs")
async def patch_prefs(request: Request, body: PrefsBody):
    app = app_of(request)
    try:
        app.prefs.update(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    app.apply_prefs()
    return _prefs_view(app)


@router.post("/prefs/preview")
async def preview_prefs(request: Request, body: PreviewBody):
    """Play a sample with the current preferences: 'speech', 'received' (the sound alone) or 'mix' (sound over speech)."""
    app = app_of(request)
    what = body.what
    if what == "received":
        app.cues.play("received")
        return {"playing": what}
    app.coaching._spawn(app.audio.speak(PREVIEW_TEXT, lambda: True, {"kind": "preview"}))
    if what == "mix":
        async def cue_mid_sentence() -> None:
            await asyncio.sleep(1.8)  # `say` + Bluetooth take ~1 s to become audible
            app.cues.play("received")
        app.coaching._spawn(cue_mid_sentence())
    return {"playing": what}


# --- diagnostics -----------------------------------------------------------------------------
def _mic_status(app) -> dict[str, Any]:
    rec = app.voice.recorder
    if hasattr(rec, "status"):
        return {"recorder": rec.name, "always_open": True, **rec.status()}
    return {"recorder": rec.name, "always_open": False}


def device_summary(app) -> dict[str, Any]:
    """Mic and remote, reduced to what the top bar shows: ok (quiet glyph), or a state worth a labelled chip."""
    mic = _mic_status(app)
    if not mic.get("always_open"):
        m = {"state": "unmanaged", "device": None, "detail": f"Mic opens per question ({mic['recorder']})"}
    elif not mic.get("open") or mic.get("error"):
        m = {"state": "none", "device": None, "detail": mic.get("error") or "No microphone available. Voice is off."}
    elif mic.get("fallback"):
        m = {"state": "fallback", "device": mic.get("active_device"),
             "detail": f"{mic.get('device') or 'Preferred mic'} unavailable. Using {mic.get('active_device')}."}
    elif mic.get("stalled"):
        m = {"state": "stalled", "device": mic.get("active_device"), "detail": "Mic is open but silent; reopening."}
    else:
        m = {"state": "ok", "device": mic.get("active_device"), "detail": f"Mic: {mic.get('active_device')}, held open"}
    m["preferred"] = mic.get("device")
    keys = app.keys.diagnostics() if app.keys else None
    if not keys or not keys.get("running"):
        r = {"state": "off", "detail": "Remote not in use (keyboard only)"}
    elif keys.get("source") != "gamepad":
        r = {"state": "keyboard", "detail": "Global keys (keyboard mode)"}
    elif keys.get("connected"):
        r = {"state": "ok", "detail": "Remote connected"}
    else:
        r = {"state": "asleep", "detail": "Remote asleep or out of range. Press any button to wake it. Space still works as talk."}
    r["reconnects"] = (keys or {}).get("reconnects", 0)
    return {"mic": m, "remote": r}


@router.get("/devices")
async def devices(request: Request):
    return device_summary(app_of(request))


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
        "mic": _mic_status(app),
        "devices": device_summary(app),
        "speech_stop_latency_ms": {"n": len(stops), "last": stops[-5:], "max": max(stops) if stops else None},
        "providers": {"configured": app.providers.configured(), "health": app.providers.health},
        "timing": summarize(marks),
        "recent_events": list(app.bus.recent)[-80:],
        "watching": app.ingest.watched_session_id,
        "telemetry": {"log_file": str(app.log_path) if app.log_path else None,
                      "store_model_io": app.settings.store_model_io,
                      "last_network_probe": app.network.last,
                      "model_calls": len(await app.store.model_calls(session_id)) if session_id else None},
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

