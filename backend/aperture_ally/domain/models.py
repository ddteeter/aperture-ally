"""Persisted domain records.

Conventions: UUID string IDs, UTC ISO timestamps for persisted events, shutter duration in seconds,
aperture as f-number, ISO numeric, dimensions orientation-normalized. Unknown stays ``None``/"unknown";
nothing here is ever defaulted to a plausible-looking camera value.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


# --- state axes -------------------------------------------------------------------------------


class ProcessingState(StrEnum):
    discovered = "discovered"
    stabilizing = "stabilizing"
    ready = "ready"
    analyzing = "analyzing"
    analyzed = "analyzed"
    failed = "failed"
    pending_retry = "pending_retry"


class CoverageState(StrEnum):
    missing = "missing"
    candidate = "candidate"
    needs_retake = "needs_retake"
    accepted = "accepted"


class AudioState(StrEnum):
    idle = "idle"
    listening = "listening"
    transcribing = "transcribing"
    preparing_response = "preparing_response"
    speaking = "speaking"
    cancelled = "cancelled"
    error = "error"


class SessionStatus(StrEnum):
    active = "active"
    paused = "paused"
    completed = "completed"


# --- value objects ----------------------------------------------------------------------------


class Region(BaseModel):
    """Normalized rectangle in the orientation-corrected image (0..1)."""

    id: str
    label: str = ""
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

    def clamp(self) -> Region:
        w = min(self.w, 1 - self.x)
        h = min(self.h, 1 - self.y)
        return self.model_copy(update={"w": max(w, 1e-4), "h": max(h, 1e-4)})


class Criterion(BaseModel):
    id: str
    text: str


# --- records ----------------------------------------------------------------------------------

Tri = Literal["unknown"]


class SetupFields(BaseModel):
    camera: str | None = None
    lens: str | None = None
    support: Literal["tripod", "handheld", "unknown"] = "unknown"
    light: Literal["continuous", "flash", "mixed", "natural", "unknown"] = "unknown"
    light_mobility: Literal["movable", "fixed_sun_or_window", "unknown"] = "unknown"
    subject_movement: Literal["stationary", "moving", "unknown"] = "unknown"
    exposure_mode: Literal["manual", "aperture_priority", "shutter_priority", "program", "unknown"] = "unknown"
    iso_mode: Literal["manual", "auto", "unknown"] = "unknown"
    available_equipment: list[str] = Field(default_factory=list)
    intended_crop: str | None = None
    desired_sharp_regions: str | None = None
    notes: str | None = None


class SetupRevision(SetupFields):
    id: str = Field(default_factory=new_id)
    session_id: str
    revision: int
    created_at: str = Field(default_factory=utcnow)


class Session(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    product: str = ""
    watch_folder: str | None = None
    output_folder: str
    active_shot_id: str | None = None
    current_setup_revision_id: str | None = None
    assess_provider: str = "mock"
    teaching_mode: bool = True
    simulated: bool = Field(False, description="Replay/simulator session: results are not hardware evidence")
    coaching_paused: bool = Field(False, description="Auto-coaching off; photos still ingested, explicit reviews allowed")
    paused_reason: str | None = None
    budget_usd: float | None = Field(None, description="Per-session spend cap (priced calls only); None = config default")
    max_model_calls: int | None = Field(None, description="Per-session paid-call cap; None = config default")
    ui_theme: Literal["studio", "daylight"] = Field("studio", description="Display theme: Studio (dark) or Daylight")
    template: str | None = Field(None, description="Shot-list template the session started from; None = unknown")
    project_id: str | None = None
    template_id: str | None = None
    template_version: int | None = Field(None, description="Template version the shot list was copied from")
    template_saved: dict[str, Any] | None = Field(
        None, description="Last save of this shoot's shot list: {template_id, name, version, as_new}")
    shoot_preferences: str = Field("", description="This shoot only ('outdoors, no backdrop'); overrides above")
    status: SessionStatus = SessionStatus.active
    watch_since: str = Field(default_factory=utcnow)
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class TemplateShot(BaseModel):
    """One shot in a reusable shoot template (copied into each shoot created from it)."""

    title: str
    purpose: str = ""
    must_show: list[str] = Field(default_factory=list)
    framing: str = ""
    criteria: list[Criterion] = Field(default_factory=list)
    sharp_regions: list[Region] = Field(default_factory=list)


class Project(BaseModel):
    """A body of work with a consistent look, e.g. 'Running blog'."""

    id: str = Field(default_factory=new_id)
    name: str
    preferences: str = Field("", description="The project's look/taste, passed to the coach")
    archived: bool = False
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class TemplateVersion(BaseModel):
    """One entry in a template's history: how it reached this version."""

    version: int
    at: str = Field(default_factory=utcnow)
    how: Literal["created", "duplicated", "edited", "from_shoot"] = "created"
    session_id: str | None = None
    session_name: str | None = None
    summary: str = ""


class ShootTemplate(BaseModel):
    """A reusable shoot for one product type ('Shoe review', 'Half tights'): its shot list and preferences."""

    id: str = Field(default_factory=new_id)
    project_id: str
    name: str
    preferences: str = Field("", description="Taste specific to this product type, passed to the coach")
    shots: list[TemplateShot] = Field(default_factory=list)
    version: int = 1
    source: str | None = Field(None, description="Built-in starter it was seeded from (running_shoe, …)")
    history: list[TemplateVersion] = Field(default_factory=list, description="Newest last")
    archived: bool = False
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class ShotRequirement(BaseModel):
    id: str = Field(default_factory=new_id)
    session_id: str
    ordinal: int = 0
    title: str
    purpose: str = ""
    must_show: list[str] = Field(default_factory=list)
    framing: str = ""
    sharp_regions: list[Region] = Field(default_factory=list)
    criteria: list[Criterion] = Field(default_factory=list)
    reference_image: str | None = None
    needs_retake: bool = False
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class Capture(BaseModel):
    id: str = Field(default_factory=new_id)
    session_id: str
    seq: int = 0
    shot_id: str | None = None
    setup_revision_id: str | None = None
    extra_shot_ids: list[str] = Field(default_factory=list)
    origin: Literal["watch", "import", "replay", "recovered", "upload"] = "watch"
    recovered: bool = False
    attribution_ambiguous: bool = False
    source_paths: list[str] = Field(default_factory=list)
    jpeg_path: str | None = None
    raw_path: str | None = None
    preview_source: Literal["jpeg", "raw_embedded", "raw_developed", "none"] | None = None
    jpeg_sha256: str | None = None
    raw_sha256: str | None = None
    pairing: dict[str, Any] = Field(default_factory=dict)
    exif: dict[str, Any] = Field(default_factory=dict)
    exif_raw: dict[str, Any] = Field(default_factory=dict, description="Full ExifTool/Pillow tags (for later features)")
    evidence: dict[str, Any] = Field(default_factory=dict)
    timings: dict[str, Any] = Field(default_factory=dict, description="ingest/evidence sub-stage timings (ms) + counters")
    width: int | None = None
    height: int | None = None
    capture_time: str | None = None
    processing_state: ProcessingState = ProcessingState.discovered
    error: str | None = None
    baseline_capture_id: str | None = None
    baseline_overridden: bool = False
    user_reported_change: str | None = None
    detected_at: str = Field(default_factory=utcnow)
    ready_at: str | None = None
    attribution_context: dict[str, Any] = Field(
        default_factory=dict, description="At detection: shot active before a recent switch, seconds since the switch")
    retry_when_online: bool = Field(False, description="Run the assessment once when the provider is reachable again")


class Assessment(BaseModel):
    id: str = Field(default_factory=new_id)
    session_id: str
    capture_id: str
    shot_id: str | None = None
    setup_revision_id: str | None = None
    baseline_capture_id: str | None = None
    kind: Literal["assess", "compare"] = "assess"
    trigger: Literal["auto", "user", "eval"] = "auto"
    prompt_version: str = ""
    provider: str = ""
    model_requested: str | None = None
    model_resolved: str | None = None
    measurements: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    exposure_note: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    model_call_ids: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    cost_estimate_usd: float | None = None
    status: Literal["queued", "running", "completed", "failed", "superseded"] = "queued"
    error: str | None = None
    repair_attempted: bool = False
    speech_status: Literal["pending", "spoken", "suppressed", "cancelled", "not_applicable"] = "pending"
    early_speech: dict[str, Any] | None = Field(
        None, description="spoken_text said while the rest streamed: {text, ready_ms, corrected}")
    context_generation: int = 0
    created_at: str = Field(default_factory=utcnow)
    completed_at: str | None = None


class Experiment(BaseModel):
    id: str = Field(default_factory=new_id)
    session_id: str
    shot_id: str | None
    baseline_capture_id: str
    baseline_assessment_id: str
    suggested_adjustment: str
    held_constant: str | None = None
    intended_effect: str | None = None
    follow_up_capture_id: str | None = None
    comparison_assessment_id: str | None = None
    comparison_outcome: Literal["improved", "worse", "mixed", "uncertain"] | None = None
    actual_change: str | None = None
    user_rating: Literal["helpful", "neutral", "harmful"] | None = None
    criterion_improved: bool | None = None
    other_criteria_worsened: bool | None = None
    lesson: str | None = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class KeeperDecision(BaseModel):
    id: str = Field(default_factory=new_id)
    session_id: str
    shot_id: str
    capture_id: str
    stored_path: str
    sha256: str
    notes: str | None = None
    criterion_notes: dict[str, str] = Field(default_factory=dict)
    source: Literal["ui", "voice"] = "ui"
    accepted_at: str = Field(default_factory=utcnow)
    revoked_at: str | None = None


class VoiceTurn(BaseModel):
    id: str = Field(default_factory=new_id)
    session_id: str
    shot_id: str | None = None
    capture_id: str | None = None
    voice_epoch: int = 0
    started_at: str = Field(default_factory=utcnow)
    duration_s: float | None = None
    transcript: str | None = None
    intent: str | None = None
    answer: str | None = None
    status: Literal[
        "recording", "transcribing", "answering", "answered", "spoken", "suppressed", "cancelled",
        "empty", "timed_out", "error",
    ] = "recording"
    error: str | None = None
    audio_path: str | None = None
    timings: dict[str, float] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict, description="clip stats, transcriber/model ids, usage")
    model_call_ids: list[str] = Field(default_factory=list)


class ModelCall(BaseModel):
    """One provider request (model or transcription) with its full input description and raw output.

    Kept for optimisation: failed/invalid raw outputs, exact context, image sizes, latency, tokens,
    and the network conditions at the time. Image bytes are not duplicated; paths point at evidence files.
    """

    id: str = Field(default_factory=new_id)
    session_id: str | None = None
    capture_id: str | None = None
    assessment_id: str | None = None
    voice_turn_id: str | None = None
    purpose: Literal["assess", "answer", "transcribe"]
    attempt: int = 0  # 0 = first call, 1 = repair
    provider: str
    model_requested: str | None = None
    model_resolved: str | None = None
    prompt_version: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)
    response_text: str | None = None
    response_id: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float | None = None
    queue_wait_ms: float | None = None
    status: Literal["ok", "invalid", "error", "unavailable", "timeout", "cancelled"] = "ok"
    validation_errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    network: dict[str, Any] | None = None
    started_at: str = Field(default_factory=utcnow)
    boot_id: str | None = None
