// Builders for Workflows screen tests.
import type { Coverage, CoverageShot, Diagnostics, Session, SessionState, SetupRevision, Shot } from "../api/types";
import { baselineCapture, shot as baseShot } from "../test/fixtures";

export function makeSession(over: Partial<Session> = {}): Session {
  return {
    id: "s1",
    name: "Trail Jacket Review",
    product: "Ridgeline shell",
    watch_folder: "/tmp/watch",
    output_folder: "/tmp/out",
    active_shot_id: "shot-1",
    current_setup_revision_id: "rev-2",
    assess_provider: "mock",
    teaching_mode: true,
    simulated: false,
    coaching_paused: false,
    paused_reason: null,
    budget_usd: null,
    max_model_calls: null,
    ui_theme: "studio",
    status: "active",
    watch_since: null,
    created_at: "2026-09-26T10:00:00Z",
    updated_at: "2026-09-26T10:00:00Z",
    ...over,
  };
}

export function makeShot(id: string, ordinal: number, title: string, over: Partial<Shot> = {}): Shot {
  return { ...baseShot, id, ordinal, title, ...over };
}

export function covShot(shot_id: string, title: string, state: string, over: Partial<CoverageShot> = {}): CoverageShot {
  return {
    shot_id,
    title,
    purpose: "",
    state,
    resolved: state === "accepted",
    captures: state === "missing" ? 0 : 2,
    latest_ai_verdict: null,
    latest_assessed_seq: null,
    keeper: null,
    keeper_problem: null,
    ...over,
  };
}

export function makeCoverage(shots: CoverageShot[]): Coverage {
  const resolved = shots.filter((s) => s.resolved).length;
  return {
    session_id: "s1",
    generated_at: "",
    shots,
    resolved,
    total: shots.length,
    unresolved: shots.filter((s) => !s.resolved).map((s) => s.title),
    complete: resolved === shots.length,
  };
}

export const setupRev: SetupRevision = {
  id: "rev-2",
  session_id: "s1",
  revision: 2,
  created_at: "2026-09-26T10:05:00Z",
  camera: "OM-1",
  lens: null,
  support: "tripod",
  light: "natural",
  light_mobility: "movable",
  subject_movement: "stationary",
  exposure_mode: "manual",
  iso_mode: "manual",
  available_equipment: ["Reflector"],
  intended_crop: null,
  desired_sharp_regions: null,
  notes: null,
};

export function makeState(over: Partial<SessionState> = {}): SessionState {
  const shots = [makeShot("shot-1", 0, "Hero"), makeShot("shot-2", 1, "Outsole"), makeShot("shot-3", 2, "Heel")];
  return {
    session: makeSession(),
    shots,
    setup: setupRev,
    setup_revisions: 2,
    captures: [baselineCapture],
    experiments: [],
    keepers: [],
    coverage: makeCoverage(shots.map((s) => covShot(s.id, s.title, "missing"))),
    pending_files: [],
    voice: { state: "idle", turn: null, repeats_ignored: 0, at: "" },
    watching: true,
    provider_health: {},
    providers_configured: { mock: true, claude: true, openai: false, gemini: true },
    ...over,
  };
}

export function makeDiag(over: Partial<Diagnostics> = {}): Diagnostics {
  return {
    checks: [
      { name: "transcription", status: "ok", detail: "mock", fix: "" },
      { name: "speech: say", status: "ok", detail: "found", fix: "" },
      { name: "input devices", status: "warn", detail: "default=None; all=[]", fix: "plug in a mic" },
    ],
    config: { assess_provider: "mock", transcriber: "mock" },
    keys: { running: false, error: null },
    voice: { state: "idle", turn: null, repeats_ignored: 0, at: "" },
    speech_backend: "say",
    speech_stop_latency_ms: { n: 0, last: [], max: null },
    providers: { configured: { mock: true, claude: true, openai: false, gemini: false }, health: {} },
    timing: {
      captures: [],
      summary: { model_call: { n: 4, p50_ms: 4100, p95_ms: 9000, max_ms: 9800 } },
      n_captures: 4,
    },
    recent_events: [{ seq: 1, type: "capture.ready", ts: "2026-09-26T10:00:00Z", payload: { seq: 1 } }],
    watching: "s1",
    ...over,
  };
}
