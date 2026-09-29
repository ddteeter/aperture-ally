// Hand-written types for the Aperture Ally backend payloads (see backend/aperture_ally/api/routes.py).
// Fields the UI does not use are still listed where cheap, but everything nullable is typed as such.

export type ProviderName = "mock" | "openai" | "gemini" | "claude";
export type UiTheme = "studio" | "daylight";
export type SessionStatus = "active" | "paused" | "completed";

export interface Session {
  id: string;
  name: string;
  product: string;
  watch_folder: string | null;
  output_folder: string;
  active_shot_id: string | null;
  current_setup_revision_id: string | null;
  assess_provider: ProviderName;
  teaching_mode: boolean;
  simulated: boolean;
  coaching_paused: boolean;
  paused_reason: string | null;
  budget_usd: number | null;
  max_model_calls: number | null;
  /** Display theme for this session: Studio (dark, indoor) or Daylight (sunlit screen). */
  ui_theme: UiTheme;
  status: SessionStatus;
  watch_since: string | null;
  created_at: string;
  updated_at: string;
  /** Shot-list template the session started from ("empty" = none); null for sessions created before it was stored. */
  template?: string | null;
  /** Project → shoot template this shoot was created from, and the template version it copied. */
  project_id?: string | null;
  template_id?: string | null;
  template_version?: number | null;
  /** Day-only notes for the coach ("Outdoors, no backdrop"); override the levels above. */
  shoot_preferences?: string;
  /** Last save of this shoot's shot list back to a template. */
  template_saved?: TemplateSaved | null;
  /** Summary counts, present in GET /sessions list items only. */
  shot_count?: number;
  capture_count?: number;
  /** Active (non-revoked) keepers. */
  keeper_count?: number;
  /** First keeper, else first photo; GET /sessions list items only. */
  cover_capture_id?: string | null;
  /** GET /sessions list items only: project › template and how the shot list relates to it. */
  origin?: SessionOriginSummary;
}

export interface TemplateSaved {
  template_id: string;
  name: string;
  version: number;
  as_new: boolean;
}

/** One difference between a shoot's shot list and its template: + new, ~ changed, − removed. */
export interface ShotListChange {
  g: "+" | "~" | "−";
  title: string;
  detail: string;
}

/** Where a shoot's shot list came from and how it now differs (GET /sessions/{id} → origin). */
export interface ShootOrigin {
  project_id: string | null;
  project_name: string | null;
  template_id: string | null;
  template_name: string | null;
  template_version: number | null;
  template_current_version: number | null;
  changes: ShotListChange[];
  saved: TemplateSaved | null;
}

export interface SessionOriginSummary {
  project_name: string | null;
  template_name: string | null;
  template_current_version: number | null;
  saved: TemplateSaved | null;
  changes: number;
}

export interface Criterion {
  id: string;
  text: string;
}

/** Normalized rectangle (0..1) in the orientation-corrected image. */
export interface Region {
  id: string;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Shot {
  id: string;
  session_id: string;
  ordinal: number;
  title: string;
  purpose: string;
  must_show: string[];
  framing: string;
  sharp_regions: Region[];
  criteria: Criterion[];
  reference_image: string | null;
  needs_retake: boolean;
  created_at: string;
  updated_at: string;
}

export type Support = "tripod" | "handheld" | "unknown";
export type Light = "continuous" | "flash" | "mixed" | "natural" | "unknown";
export type LightMobility = "movable" | "fixed_sun_or_window" | "unknown";
export type SubjectMovement = "stationary" | "moving" | "unknown";
export type ExposureMode = "manual" | "aperture_priority" | "shutter_priority" | "program" | "unknown";
export type IsoMode = "manual" | "auto" | "unknown";

export interface SetupFields {
  camera: string | null;
  lens: string | null;
  support: Support;
  light: Light;
  light_mobility: LightMobility;
  subject_movement: SubjectMovement;
  exposure_mode: ExposureMode;
  iso_mode: IsoMode;
  available_equipment: string[];
  intended_crop: string | null;
  desired_sharp_regions: string | null;
  notes: string | null;
}

export interface SetupRevision extends SetupFields {
  id: string;
  session_id: string;
  revision: number;
  created_at: string;
}

export interface Exif {
  source?: string;
  camera_make?: string | null;
  camera_model?: string | null;
  lens?: string | null;
  exposure_time_s?: number | null;
  f_number?: number | null;
  iso?: number | null;
  focal_length_mm?: number | null;
  flash_fired?: boolean | null;
  exposure_program?: string | null;
  datetime_original?: string | null;
  orientation?: number | null;
  exposure_known?: boolean;
  metadata_available?: boolean;
  /** Frame of an in-camera bracket (Olympus/OM). Only shot 1, the base exposure, is auto-coached. */
  bracket?: { kind: string; shot: number } | null;
}

export interface Crop {
  id: string;
  label: string;
  source: "user" | "auto" | string;
  rect: [number, number, number, number];
  px_rect: [number, number, number, number];
  scale: number;
  native_resolution: boolean;
}

export interface LumaStats {
  mean_luminance: number;
  p01_luminance: number;
  p99_luminance: number;
  highlight_clip_fraction: number;
  shadow_clip_fraction: number;
  channel_highlight_clip: Record<string, number>;
  channel_shadow_clip: Record<string, number>;
  laplacian_var: number;
  tenengrad_mean: number;
  gradient_p90: number;
}

export interface GlobalMeasurements extends LumaStats {
  histogram: number[];
}

export interface RegionMeasurements extends LumaStats {
  rect: number[];
  px_size: number[];
  histogram?: number[];
}

/** Plain-language histogram reading from fixed rules (backend imaging/interpret.py). */
export type InsightSeverity = "problem" | "warn" | "info" | "ok";
export type InsightZone = "clip_low" | "shadows" | "midtones" | "highlights" | "clip_high";

export interface InsightFinding {
  scope: string;
  severity: InsightSeverity;
  zone: InsightZone;
  headline: string;
  detail: string;
}

export interface ScopeInsight {
  scope: string;
  region_id?: string;
  headline: string;
  shape: string;
  severity: InsightSeverity;
  zones: { shadows?: number; midtones?: number; highlights?: number };
  highlight_clip: number;
  shadow_clip: number;
  findings: InsightFinding[];
}

export interface HistogramInsights {
  summary: string;
  regions: ScopeInsight[];
  overall: ScopeInsight;
  how_to_read: string[];
  caveat: string;
}

export interface Measurements {
  image: {
    width: number;
    height: number;
    orientation_tag: number | null;
    icc_profile: string | null;
    color_assumption: string;
  };
  global: GlobalMeasurements;
  regions: Record<string, RegionMeasurements>;
  notes: Record<string, string>;
  caveats: string[];
}

export interface Evidence {
  available: boolean;
  width: number | null;
  height: number | null;
  crops: Crop[];
  measurements: Measurements | null;
  has_clip_overlay?: boolean;
  /** zone_* alpha masks can be requested (generated on first request). */
  has_zone_masks?: boolean;
}

export type Verdict = "usable_candidate" | "needs_retake" | "uncertain" | string;
export type CriterionOutcome = "pass" | "fail" | "uncertain" | string;
export type ComparisonOutcome = "improved" | "worse" | "mixed" | "uncertain" | string;

export interface CriterionResult {
  criterion_id: string;
  result: CriterionOutcome;
  evidence: string;
}

export interface Observation {
  region_id: string | null;
  observation: string;
  evidence_source: string;
  severity: string;
}

export interface PrimaryAction {
  instruction: string;
  explanation: string;
  expected_effect: string;
  tradeoff: string | null;
  prerequisites: string[];
  hold_constant: string | null;
  exposure_target: { f_number: number | null; iso: number | null; [k: string]: unknown } | null;
}

export interface Comparison {
  baseline_capture_id: string;
  outcome: ComparisonOutcome;
  evidence: string;
}

export interface AssessmentResult {
  verdict: Verdict;
  criterion_results: CriterionResult[];
  observations: Observation[];
  primary_action: PrimaryAction | null;
  alternative_causes: string[];
  /** Issues probably fixable in editing (RAW-aware); the coach never spends its one action on these. Older results lack it. */
  fixable_in_post?: string[];
  comparison: Comparison | null;
  question_for_user: string | null;
  teaching_prompt: string | null;
  spoken_text: string;
}

export interface ExposureNote {
  applicable: boolean;
  reasons: string[];
  old?: { duration_s: number; f_number: number; iso: number } | null;
  new_f_number?: number | null;
  new_iso?: number | null;
  exact_duration_s?: number | null;
  rounded_duration_s?: number | null;
  rounded_label?: string | null;
  stops_change?: number | null;
  note: string | null;
}

export type AssessmentStatus = "queued" | "running" | "completed" | "failed" | "superseded" | string;

export interface Assessment {
  id: string;
  session_id: string;
  capture_id: string;
  shot_id: string | null;
  setup_revision_id: string | null;
  baseline_capture_id: string | null;
  kind: "assess" | "compare" | string;
  trigger: string;
  prompt_version: string;
  provider: string;
  model_requested: string | null;
  model_resolved: string | null;
  measurements: Measurements | null;
  evidence: Crop[];
  result: AssessmentResult | null;
  exposure_note: ExposureNote | null;
  warnings: string[];
  timings: Record<string, number>;
  usage: { input_tokens?: number; output_tokens?: number; [k: string]: number | undefined } | null;
  cost_estimate_usd: number | null;
  status: AssessmentStatus;
  error: string | null;
  repair_attempted: boolean;
  speech_status: string | null;
  /** The sentence spoken while the rest streamed in, and whether the final result corrected it. */
  early_speech?: { text: string; ready_ms: number | null; corrected: boolean } | null;
  context_generation: number;
  created_at: string;
  completed_at: string | null;
}

export type ProcessingState =
  | "discovered"
  | "stabilizing"
  | "ready"
  | "analyzing"
  | "analyzed"
  | "failed"
  | "pending_retry"
  | string;

export interface Capture {
  id: string;
  session_id: string;
  seq: number;
  shot_id: string | null;
  setup_revision_id: string | null;
  extra_shot_ids: string[];
  origin: string;
  recovered: boolean;
  attribution_ambiguous: boolean;
  source_paths: string[];
  jpeg_path: string | null;
  raw_path: string | null;
  preview_source: string | null;
  jpeg_sha256: string | null;
  raw_sha256: string | null;
  pairing: Record<string, unknown>;
  exif: Exif;
  width: number | null;
  height: number | null;
  capture_time: string | null;
  processing_state: ProcessingState;
  error: string | null;
  baseline_capture_id: string | null;
  baseline_overridden: boolean;
  user_reported_change: string | null;
  detected_at: string | null;
  ready_at: string | null;
  evidence: Evidence;
  source_names: string[];
  jpeg_name: string | null;
  raw_name: string | null;
  latest_assessment: Assessment | null;
  histogram_insights?: HistogramInsights;
  histogram_changes?: { baseline_seq: number; changes: string[] };
  /** Measured before/after numbers against the baseline (present when the capture has a baseline with evidence). */
  comparison_metrics?: ComparisonMetrics | null;
  /** When attribution is ambiguous: the shot this capture more likely belongs to. */
  attribution_hint?: AttributionHint | null;
  /** True while an automatic retry is waiting for the provider to come back online. */
  retry_when_online?: boolean;
}

/** Framing similarity between two captures, 0..1 (1 = same framing). Below `FRAMING_COMPARABLE` a side-by-side is unfair. */
export interface FramingMatch {
  score: number;
  comparable: boolean;
}

export interface ScopeDelta {
  /** Region id, or "global" for the whole frame. */
  scope: string;
  label: string;
  /** Relative sharpness change in percent (laplacian variance ratio), e.g. +36. Null for global or if unmeasurable. */
  sharpness_change_pct: number | null;
  mean_before: number;
  mean_after: number;
  highlight_clip_before: number;
  highlight_clip_after: number;
  shadow_clip_before: number;
  shadow_clip_after: number;
  /** Region histograms (same binning as measurements) for overlaying before/after. */
  histogram_before: number[] | null;
  histogram_after: number[] | null;
}

export interface ComparisonMetrics {
  baseline_capture_id: string;
  baseline_seq: number;
  framing: FramingMatch | null;
  /** Exposure change in EV from EXIF; only when both captures are manual exposure with known values. Positive = brighter. */
  ev_delta: number | null;
  ev_note: string | null;
  regions: ScopeDelta[];
  global: ScopeDelta | null;
}

export interface AttributionHint {
  shot_id: string;
  shot_title: string;
  /** Capture in that shot whose framing matched best. */
  matched_capture_seq: number | null;
  framing_score: number | null;
  seconds_after_switch: number | null;
}

/** GET /captures/{cid}/baseline-candidates — earlier captures of the same shot ranked for "Compare with…". */
export interface BaselineCandidate {
  capture_id: string;
  seq: number;
  verdict: Verdict | null;
  framing: FramingMatch | null;
  is_current_baseline: boolean;
}

export interface SetupRevisionSummary extends SetupRevision {
  capture_count: number;
  first_seq: number | null;
  last_seq: number | null;
}

export type ZoneName = "clip_low" | "shadows" | "midtones" | "highlights" | "clip_high";

export interface Experiment {
  id: string;
  session_id: string;
  shot_id: string | null;
  baseline_capture_id: string;
  baseline_assessment_id: string | null;
  suggested_adjustment: string;
  held_constant: string | null;
  intended_effect: string | null;
  follow_up_capture_id: string | null;
  comparison_assessment_id: string | null;
  comparison_outcome: ComparisonOutcome | null;
  actual_change: string | null;
  user_rating: "helpful" | "neutral" | "harmful" | null;
  criterion_improved: boolean | null;
  other_criteria_worsened: boolean | null;
  lesson: string | null;
  created_at: string;
  updated_at: string;
}

export type ExperimentPatch = Partial<
  Pick<Experiment, "actual_change" | "user_rating" | "criterion_improved" | "other_criteria_worsened" | "lesson">
>;

/** GET /captures/{cid}: capture + all assessments + related experiments. */
export interface CaptureDetail extends Capture {
  assessments: Assessment[];
  experiments: Experiment[];
  is_latest_for_shot: boolean;
}

export interface Keeper {
  id: string;
  session_id: string;
  shot_id: string;
  capture_id: string;
  stored_path: string | null;
  sha256: string | null;
  notes: string | null;
  criterion_notes: Record<string, string>;
  source: string;
  accepted_at: string;
  revoked_at: string | null;
}

export interface CoverageKeeper extends Keeper {
  file_verified?: boolean;
  capture_seq?: number | null;
}

export type CoverageState = "missing" | "candidate" | "needs_retake" | "accepted" | string;

export interface CoverageShot {
  shot_id: string;
  title: string;
  purpose: string;
  state: CoverageState;
  resolved: boolean;
  captures: number;
  latest_ai_verdict: Verdict | null;
  latest_assessed_seq: number | null;
  keeper: CoverageKeeper | null;
  keeper_problem: string | null;
}

export interface Coverage {
  session_id: string;
  generated_at: string;
  shots: CoverageShot[];
  resolved: number;
  total: number;
  unresolved: string[];
  complete: boolean;
}

export interface PendingFile {
  /** Stable key for the read-again / skip endpoints. */
  key: string;
  name: string;
  status: "discovered" | "stabilizing" | "pending_retry" | "failed" | string;
  note: string | null;
}

export type VoiceStateName =
  | "idle"
  | "listening"
  | "transcribing"
  | "preparing_response"
  | "speaking"
  | "cancelled"
  | "error";

export interface VoiceTurn {
  id: string;
  session_id: string | null;
  shot_id: string | null;
  capture_id: string | null;
  voice_epoch: number;
  started_at: string;
  duration_s: number | null;
  transcript: string | null;
  intent: string | null;
  answer: string | null;
  status: string;
  error: string | null;
  audio_path: string | null;
  timings: Record<string, number>;
}

export interface VoiceSnapshot {
  state: VoiceStateName | string;
  turn: VoiceTurn | null;
  repeats_ignored: number;
  at: string;
  /** Speech-to-text backend ("openai" | "mock"); always a cloud call when not the mock. */
  transcriber?: string | null;
}

export interface ProviderHealth {
  ok: boolean;
  at: string;
  error?: string | null;
}

/** GET /sessions/{sid}: the authoritative snapshot the UI renders from. */
export interface SessionState {
  session: Session;
  shots: Shot[];
  setup: SetupRevision | null;
  setup_revisions: number;
  captures: Capture[];
  experiments: Experiment[];
  keepers: Keeper[];
  coverage: Coverage;
  pending_files: PendingFile[];
  voice: VoiceSnapshot;
  watching: boolean;
  provider_health: Record<string, ProviderHealth>;
  providers_configured: Record<ProviderName, boolean>;
  pending_change?: string | null;
  usage?: SessionUsage;
  /** When the watch folder last produced a file (ISO time), for "last file 12 s ago". */
  last_file_at?: string | null;
  origin?: ShootOrigin;
}

/** Paid-call usage and caps for the session (mock calls never count). */
export interface SessionUsage {
  paid_calls: number;
  capped_calls: number;
  max_model_calls: number | null;
  estimated_cost_usd: number;
  budget_usd: number | null;
  unpriced_calls: number;
  exceeded: boolean;
  reason: string | null;
  note: string | null;
}

export interface DoctorCheck {
  name: string;
  status: "ok" | "warn" | "fail" | string;
  detail: string;
  fix: string;
}

export interface KeyEvent {
  kind: string;
  key: string;
  t: number;
  hold_ms?: number;
  [k: string]: unknown;
}

export interface KeysDiagnostics {
  running: boolean;
  error: string | null;
  ptt_key?: string;
  mode?: string;
  held?: boolean;
  events?: KeyEvent[];
  learn_waiting?: boolean;
  learned?: string | null;
}

export interface TimingStat {
  n: number;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
  mean_ms?: number | null;
}

export interface TimingSummary {
  captures: Array<{ capture_id: string; stages: string[]; [interval: string]: unknown }>;
  summary: Record<string, TimingStat>;
  n_captures: number;
}

export interface Diagnostics {
  checks: DoctorCheck[];
  config: Record<string, unknown>;
  keys: KeysDiagnostics;
  voice: VoiceSnapshot;
  speech_backend: string;
  speech_stop_latency_ms: { n: number; last: number[]; max: number | null };
  providers: {
    configured: Record<ProviderName, boolean>;
    health: Record<string, ProviderHealth>;
  };
  timing: TimingSummary;
  recent_events: CoachEvent[];
  watching: string | null;
}

export interface CoachEvent {
  seq: number;
  type: string;
  ts: string;
  session_id?: string | null;
  capture_id?: string | null;
  payload: Record<string, unknown>;
}

// --- request bodies ---------------------------------------------------------------------------

export interface SessionCreate {
  name: string;
  product?: string;
  watch_folder?: string | null;
  template?: TemplateName;
  assess_provider?: ProviderName | null;
  teaching_mode?: boolean;
  simulated?: boolean;
  ui_theme?: UiTheme;
  setup?: Partial<SetupFields> | null;
  template_id?: string | null;
  project_id?: string | null;
  shoot_preferences?: string;
}

export type TemplateName = "running_shoe" | "running_apparel" | "empty";

export type SessionPatch = Partial<
  Pick<
    Session,
    | "name"
    | "product"
    | "watch_folder"
    | "assess_provider"
    | "teaching_mode"
    | "status"
    | "coaching_paused"
    | "budget_usd"
    | "max_model_calls"
    | "ui_theme"
    | "shoot_preferences"
  >
>;

export type ShotPatch = Partial<
  Pick<Shot, "title" | "purpose" | "must_show" | "framing" | "sharp_regions" | "criteria" | "needs_retake" | "ordinal">
>;

export interface CapturePatch {
  shot_id?: string | null;
  extra_shot_ids?: string[];
  baseline_capture_id?: string | null;
  user_reported_change?: string | null;
}

export interface ImportBody {
  paths?: string[];
  shot_id?: string | null;
  auto_coach?: boolean;
  replay?: "basic_loop" | "ingest_stress" | "stale_switch" | string;
}

export interface VoiceBody {
  session_id?: string | null;
  capture_id?: string | null;
  source?: string;
}

export type MockFailMode = "none" | "invalid_once" | "invalid_always" | "unavailable" | "slow";

/** zone_<ZoneName> is an alpha mask PNG (opaque where the pixel falls in that tonal zone), colourised in CSS via mask-image. */
export type ImageKind = "overview" | "thumb" | "original" | "clip_overlay" | `zone_${ZoneName}` | `crop_${string}`;

/** The owner's audio preferences, changed live from the Coaching popover (server: aperture_ally/prefs.py). */
export interface AudioPrefs {
  speech_rate_wpm: number;
  received_sound: string;
  cue_volume: number;
  /** Your defaults: taste across all projects. */
  my_preferences?: string;
}

/** GET /devices: the mic and remote reduced to what the top bar shows. */
export interface DeviceSummary {
  mic: { state: "ok" | "fallback" | "none" | "stalled" | "unmanaged"; device: string | null; preferred: string | null; detail: string };
  remote: { state: "ok" | "asleep" | "keyboard" | "off"; detail: string; reconnects: number };
}

export interface AudioPrefsView {
  prefs: AudioPrefs;
  defaults: AudioPrefs;
  /** macOS system sounds available for the received cue. */
  sounds: string[];
  speech_rate_range: [number, number];
  cue_volume_range: [number, number];
  /** sound | speech | none, from APERTURE_ALLY_RECEIVED_CUE. */
  received_cue: string;
  speech_backend: string;
}

// --- projects → shoot templates → shoots (server: aperture_ally/projects.py) ----------------------

export interface TemplateShot {
  title: string;
  purpose: string;
  must_show: string[];
  framing: string;
  criteria: Criterion[];
  sharp_regions: Region[];
}

export interface ShootTemplate {
  id: string;
  project_id: string;
  name: string;
  preferences: string;
  shots: TemplateShot[];
  version: number;
  /** Built-in starter it was seeded from (running_shoe, running_apparel), else null. */
  source: string | null;
  /** How it reached each version, oldest first. */
  history: TemplateVersion[];
  archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface TemplateVersion {
  version: number;
  at: string;
  how: "created" | "duplicated" | "edited" | "from_shoot";
  session_id: string | null;
  session_name: string | null;
  summary: string;
}

/** In the project overview: no shots, only the latest history entry, plus usage. */
export type TemplateSummary = Omit<ShootTemplate, "shots"> & {
  shot_count: number;
  shot_titles: string[];
  shoot_count: number;
  last_used: string | null;
};

export interface Project {
  id: string;
  name: string;
  preferences: string;
  archived: boolean;
  created_at: string;
  updated_at: string;
  shoot_count: number;
  last_used: string | null;
  /** Empty for archived projects. */
  templates: TemplateSummary[];
}

/** One stored model call (request + response) behind an assessment: "What the coach saw". */
export interface ModelCallView {
  id: string;
  purpose: string;
  attempt: number;
  provider: string;
  model_requested: string | null;
  model_resolved: string | null;
  prompt_version: string | null;
  status: string;
  latency_ms: number | null;
  usage: Record<string, number>;
  validation_errors: string[];
  request: {
    instructions?: string;
    context?: Record<string, unknown>;
    images?: { role: string; kind: string; region_id: string; label: string; bytes?: number }[];
    image_bytes_total?: number;
  };
  response_text: string | null;
}
