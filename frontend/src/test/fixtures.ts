import type { Assessment, AppCtxLike, Capture, Experiment, Shot } from "./fixtureTypes";

export const shot: Shot = {
  id: "shot-1",
  session_id: "s1",
  ordinal: 0,
  title: "Upper texture (mesh close-up)",
  purpose: "Let readers see the mesh weave.",
  must_show: ["mesh"],
  framing: "tight",
  sharp_regions: [{ id: "r1", label: "forefoot mesh", x: 0.3, y: 0.35, w: 0.25, h: 0.25 }],
  criteria: [
    { id: "c1", text: "Mesh weave is sharp" },
    { id: "c2", text: "No blown highlights on the mesh" },
  ],
  reference_image: null,
  needs_retake: false,
  created_at: "2026-09-26T10:00:00Z",
  updated_at: "2026-09-26T10:00:00Z",
};

function capture(id: string, seq: number, extra: Partial<Capture> = {}): Capture {
  return {
    id,
    session_id: "s1",
    seq,
    shot_id: shot.id,
    setup_revision_id: null,
    extra_shot_ids: [],
    origin: "watch",
    recovered: false,
    attribution_ambiguous: false,
    source_paths: [],
    jpeg_path: null,
    raw_path: null,
    preview_source: "jpeg",
    jpeg_sha256: null,
    raw_sha256: null,
    pairing: {},
    exif: {},
    width: 2400,
    height: 1600,
    capture_time: null,
    processing_state: "analyzed",
    error: null,
    baseline_capture_id: null,
    baseline_overridden: false,
    user_reported_change: null,
    detected_at: null,
    ready_at: null,
    evidence: { available: true, width: 2400, height: 1600, crops: [], measurements: null },
    source_names: [`P${seq}.JPG`],
    jpeg_name: `P${seq}.JPG`,
    raw_name: null,
    latest_assessment: null,
    ...extra,
  };
}

export function assessment(extra: Partial<Assessment> = {}): Assessment {
  return {
    id: "a2",
    session_id: "s1",
    capture_id: "cap-2",
    shot_id: shot.id,
    setup_revision_id: null,
    baseline_capture_id: "cap-1",
    kind: "compare",
    trigger: "auto",
    prompt_version: "coach-2026-09-26.1",
    provider: "mock",
    model_requested: "mock-heuristic-v1",
    model_resolved: "mock-heuristic-v1",
    measurements: null,
    evidence: [],
    result: {
      verdict: "usable_candidate",
      criterion_results: [
        { criterion_id: "c1", result: "pass", evidence: "regional sharpness indicator not unusually low" },
        { criterion_id: "c2", result: "uncertain", evidence: "clipping low; visibility not judged" },
      ],
      observations: [
        { region_id: "r1", observation: "Highlight clipping is 0.0% of forefoot mesh.", evidence_source: "measurement", severity: "info" },
      ],
      primary_action: {
        instruction: "Keep this setup and take a safety frame.",
        explanation: "The glare is gone.",
        expected_effect: "A second usable frame.",
        tradeoff: null,
        prerequisites: [],
        hold_constant: "everything",
        exposure_target: null,
      },
      alternative_causes: [],
      comparison: { baseline_capture_id: "cap-1", outcome: "improved", evidence: "glare metric 0.552 → 0" },
      question_for_user: null,
      teaching_prompt: "What made this frame work for the reader?",
      spoken_text: "Mock coach: Better. The glare is gone.",
    },
    exposure_note: { applicable: false, reasons: ["light is flash: equivalence does not hold"], note: null },
    warnings: [],
    timings: { model_ms: 151, total_ms: 155.7 },
    usage: { input_tokens: 0, output_tokens: 0 },
    cost_estimate_usd: null,
    status: "completed",
    error: null,
    repair_attempted: false,
    speech_status: "spoken",
    context_generation: 3,
    created_at: "2026-09-26T10:00:00Z",
    completed_at: "2026-09-26T10:00:01Z",
    ...extra,
  };
}

export const baselineCapture = capture("cap-1", 1);
export function followUpCapture(a: Assessment | null, extra: Partial<Capture> = {}) {
  return capture("cap-2", 2, { baseline_capture_id: "cap-1", latest_assessment: a, ...extra });
}

export const experiment: Experiment = {
  id: "exp-1",
  session_id: "s1",
  shot_id: shot.id,
  baseline_capture_id: "cap-1",
  baseline_assessment_id: "a1",
  suggested_adjustment: "Move the light about a hand-width camera-left.",
  held_constant: "camera position",
  intended_effect: "Less glare on the mesh.",
  follow_up_capture_id: "cap-2",
  comparison_assessment_id: "a2",
  comparison_outcome: "improved",
  actual_change: null,
  user_rating: null,
  criterion_improved: null,
  other_criteria_worsened: null,
  lesson: null,
  created_at: "2026-09-26T10:00:00Z",
  updated_at: "2026-09-26T10:00:00Z",
};

export type { AppCtxLike };

// --- session snapshot (coach panel / voice bar tests) -------------------------------------------
export const makeCapture = capture;

export function sessionState(extra: Partial<import("../api/types").SessionState> = {}): import("../api/types").SessionState {
  return {
    session: {
      id: "s1",
      name: "Trail shoe review",
      product: "Trail shoe",
      watch_folder: "/tmp/watch",
      output_folder: "/tmp/out",
      active_shot_id: shot.id,
      current_setup_revision_id: null,
      assess_provider: "claude",
      teaching_mode: true,
      simulated: false,
      coaching_paused: false,
      paused_reason: null,
      budget_usd: null,
      max_model_calls: 40,
      ui_theme: "studio",
      status: "active",
      watch_since: null,
      created_at: "2026-09-26T10:00:00Z",
      updated_at: "2026-09-26T10:00:00Z",
    },
    shots: [shot],
    setup: null,
    setup_revisions: 1,
    captures: [],
    experiments: [],
    keepers: [],
    coverage: { session_id: "s1", generated_at: "2026-09-26T10:00:00Z", shots: [], resolved: 0, total: 1, unresolved: [], complete: false },
    pending_files: [],
    voice: { state: "idle", turn: null, repeats_ignored: 0, at: "2026-09-26T10:00:00Z" },
    watching: true,
    provider_health: {},
    providers_configured: { mock: true, openai: false, gemini: false, claude: true },
    pending_change: null,
    usage: {
      paid_calls: 12,
      capped_calls: 12,
      max_model_calls: 40,
      estimated_cost_usd: 0.34,
      budget_usd: null,
      unpriced_calls: 0,
      exceeded: false,
      reason: null,
      note: null,
    },
    ...extra,
  };
}
