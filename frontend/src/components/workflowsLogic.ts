// Pure helpers for the Workflows screens (Coverage, Sessions, Shot list, Setup, Diagnostics).
import type {
  Capture,
  Coverage,
  CoverageShot,
  Diagnostics,
  DoctorCheck,
  SessionState,
  SetupFields,
  SetupRevisionSummary,
  Shot,
  TemplateName,
} from "../api/types";

// --- coverage ---------------------------------------------------------------------------------

export interface CoverageCounts {
  keepers: number;
  candidates: number;
  retakes: number;
  missing: number;
}

export function coverageCounts(shots: CoverageShot[]): CoverageCounts {
  const n = (st: string) => shots.filter((s) => s.state === st).length;
  return { keepers: n("accepted"), candidates: n("candidate"), retakes: n("needs_retake"), missing: n("missing") };
}

export function coverageHeadline(cov: Coverage): string {
  if (cov.total === 0) return "No shots yet";
  if (cov.complete) return "Ready to export";
  const left = cov.total - cov.resolved;
  return `Not yet — ${left} ${left === 1 ? "shot" : "shots"} still missing`;
}

/** Link text on a coverage card: what to do next for this shot. */
export function coverageCta(state: string): string {
  if (state === "accepted") return "Change keeper →";
  if (state === "needs_retake") return "Retake →";
  if (state === "candidate") return "Pick a keeper →";
  return "Shoot this →";
}

export function shutter(t: number | null | undefined): string | null {
  if (t == null || !(t > 0)) return null;
  if (t >= 1) return `${Number(t.toFixed(1))} s`;
  return `1/${Math.round(1 / t)} s`;
}

/** "#3 · 1/125 s · f/5.6": seq plus whatever exposure EXIF is known. */
export function captureMeta(c: Capture | undefined, seq: number | null | undefined): string {
  const parts = [`#${seq ?? c?.seq ?? "?"}`];
  const s = shutter(c?.exif?.exposure_time_s);
  if (s) parts.push(s);
  if (c?.exif?.f_number) parts.push(`f/${c.exif.f_number}`);
  if (c?.exif?.iso) parts.push(`ISO ${c.exif.iso}`);
  return parts.join(" · ");
}

/** Second line of a coverage card. */
export function coverageMeta(s: CoverageShot, captures: Capture[]): string {
  if (s.state === "accepted" && s.keeper) {
    return captureMeta(
      captures.find((c) => c.id === s.keeper!.capture_id),
      s.keeper.capture_seq,
    );
  }
  if (s.captures === 0) return "No photos yet";
  const photos = `${s.captures} ${s.captures === 1 ? "photo" : "photos"}`;
  if (s.state === "needs_retake") return `${s.captures} ${s.captures === 1 ? "attempt" : "attempts"}${s.latest_assessed_seq != null ? ` · last #${s.latest_assessed_seq}` : ""}`;
  if (s.latest_assessed_seq != null) return `${photos} · latest #${s.latest_assessed_seq}`;
  return photos;
}

const EXPORT_LABELS: Record<string, string> = {
  json: "JSON",
  markdown: "Markdown",
  contact_sheet: "Contact sheet",
  timing_json: "Timing JSON",
  timing_markdown: "Timing Markdown",
};
export function exportLabel(key: string): string {
  return EXPORT_LABELS[key] ?? key.replace(/_/g, " ");
}

export function fileName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

// --- sessions ---------------------------------------------------------------------------------

/** Shot counts per template, mirrored from backend/aperture_ally/templates.py (no endpoint lists them). */
export const TEMPLATE_SHOTS: Record<TemplateName, number> = { running_apparel: 8, running_shoe: 6, empty: 0 };

export interface WatchNote {
  tone: "ok" | "warn";
  text: string;
}
export function watchFolderNote(value: string): WatchNote {
  const v = value.trim();
  if (!v) return { tone: "ok", text: "✓ Default: a new folder in the app's data directory" };
  if (!(v.startsWith("/") || v.startsWith("~"))) return { tone: "warn", text: "! Use a full path, starting with / or ~" };
  if (/[\n\t]/.test(value)) return { tone: "warn", text: "! The path contains a line break or tab" };
  return { tone: "ok", text: "✓ Created if it doesn't exist. Point OM Capture at the same folder." };
}

// --- shot list --------------------------------------------------------------------------------

export function sortedShots(shots: Shot[]): Shot[] {
  return shots
    .map((s, i) => ({ s, i }))
    .sort((a, b) => a.s.ordinal - b.s.ordinal || a.i - b.i)
    .map((x) => x.s);
}

/** Move one shot up/down and return the ordinal patches needed (shots renumbered 0..n-1). */
export function reorderPatches(shots: Shot[], id: string, dir: -1 | 1): { id: string; ordinal: number }[] {
  const list = sortedShots(shots);
  const i = list.findIndex((s) => s.id === id);
  const j = i + dir;
  if (i < 0 || j < 0 || j >= list.length) return [];
  [list[i], list[j]] = [list[j], list[i]];
  return list.flatMap((s, k) => (s.ordinal === k ? [] : [{ id: s.id, ordinal: k }]));
}

// --- setup ------------------------------------------------------------------------------------

export const SETUP_LABELS: Record<keyof SetupFields, string> = {
  camera: "Camera",
  lens: "Lens",
  support: "Camera support",
  light: "Light type",
  light_mobility: "Light position",
  subject_movement: "Subject movement",
  exposure_mode: "Exposure",
  iso_mode: "ISO",
  available_equipment: "Gear",
  intended_crop: "Intended crop",
  desired_sharp_regions: "Sharp regions",
  notes: "Notes",
};

const ENUM_KEYS = new Set<keyof SetupFields>(["support", "light", "light_mobility", "subject_movement", "exposure_mode", "iso_mode"]);

/** One line on what a revision changed compared with the one before. */
export function setupChanges(prev: SetupFields | null, cur: SetupFields): string {
  if (!prev) return "Session start";
  const keys = (Object.keys(SETUP_LABELS) as (keyof SetupFields)[]).filter(
    (k) => JSON.stringify(prev[k] ?? null) !== JSON.stringify(cur[k] ?? null),
  );
  if (keys.length === 0) return "No changes";
  const say = (k: keyof SetupFields) =>
    ENUM_KEYS.has(k) ? `${SETUP_LABELS[k]} → ${String(cur[k]).replace(/_/g, " ")}` : `${SETUP_LABELS[k]} changed`;
  const shown = keys.slice(0, 2).map(say).join(" · ");
  return keys.length > 2 ? `${shown} · +${keys.length - 2} more` : shown;
}

export function revisionPhotos(r: Pick<SetupRevisionSummary, "capture_count" | "first_seq" | "last_seq">): string {
  if (!r.capture_count || r.first_seq == null) return "no photos yet";
  if (r.last_seq == null || r.last_seq === r.first_seq) return `photo #${r.first_seq}`;
  return `photos #${r.first_seq}–#${r.last_seq}`;
}

// --- diagnostics ------------------------------------------------------------------------------

export interface HealthRow {
  /** true = ok, null = check, false = problem */
  ok: boolean | null;
  label: string;
  detail: string;
}

export function ago(iso: string | null | undefined, now: number): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 90) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 90) return `${m} min`;
  return `${Math.round(m / 60)} h`;
}

const checkOk = (c: DoctorCheck | undefined): boolean | null =>
  !c ? null : c.status === "ok" ? true : c.status === "fail" ? false : null;

function hhmm(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function healthRows(diag: Diagnostics | null, state: SessionState | null, now: number): HealthRow[] {
  const check = (name: string) => diag?.checks.find((c) => c.name === name);
  const rows: HealthRow[] = [];

  if (!state) {
    rows.push({ ok: null, label: "Watch folder", detail: "no session open" });
  } else {
    const a = ago(state.last_file_at, now);
    rows.push({
      ok: state.watching ? true : null,
      label: a ? `Watch folder: last file ${a} ago` : "Watch folder: no files yet",
      detail: state.watching ? state.session.watch_folder ?? "watching" : "not watching (session not active)",
    });
  }

  const provider = state?.session.assess_provider ?? (diag?.config.assess_provider as string | undefined);
  if (provider === "mock") {
    rows.push({ ok: true, label: "Network", detail: "mock provider · no network needed" });
  } else if (provider && diag) {
    const configured = diag.providers.configured[provider as keyof typeof diag.providers.configured];
    const h = diag.providers.health[provider];
    if (configured === false) rows.push({ ok: false, label: "Network", detail: `${provider} not configured` });
    else if (h?.ok) rows.push({ ok: true, label: "Network", detail: `${provider} · last call OK ${hhmm(h.at)}` });
    else if (h) rows.push({ ok: false, label: "Network", detail: `${provider} unavailable${h.error ? `: ${h.error}` : ""}` });
    else rows.push({ ok: null, label: "Network", detail: `${provider} · no calls yet` });
  } else {
    rows.push({ ok: null, label: "Network", detail: "not reported" });
  }

  const tr = check("transcription");
  const transcriber = diag?.config.transcriber as string | undefined;
  rows.push({
    ok: checkOk(tr),
    label: "Transcription",
    detail: tr ? [transcriber, tr.status === "ok" ? "reachable" : tr.detail].filter(Boolean).join(" · ") : "not reported",
  });

  const sp = check("speech: say");
  rows.push({
    ok: sp ? checkOk(sp) : diag ? true : null,
    label: "Speech out",
    detail: diag ? [diag.speech_backend, sp && sp.status !== "ok" ? sp.detail : null].filter(Boolean).join(" · ") : "not reported",
  });

  const mic = check("input devices");
  rows.push({ ok: checkOk(mic), label: "Microphone", detail: mic ? mic.detail.split(";")[0] : "not reported" });

  const u = state?.usage;
  if (!u) rows.push({ ok: null, label: "Budget", detail: "not reported" });
  else {
    const calls = `${u.paid_calls}${u.max_model_calls != null ? ` / ${u.max_model_calls}` : ""} paid calls`;
    const cost = `≈ $${u.estimated_cost_usd.toFixed(2)}${u.budget_usd != null ? ` of $${u.budget_usd.toFixed(2)}` : ""}`;
    rows.push({ ok: u.exceeded ? false : true, label: "Budget", detail: u.exceeded ? u.reason ?? "limit reached" : `${calls} · ${cost}` });
  }
  return rows;
}

export const TIMING_LABELS: Record<string, string> = {
  detect_to_ready: "Capture → received",
  "local_feedback (ready→evidence)": "Local measurements",
  model_call: "Coach verdict (model call)",
  ready_to_validated: "Received → verdict",
  "ready_to_speech_process (first useful speech proxy)": "Received → speech process started",
};

export function seconds(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return "—";
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
}

export const REPLAYS = [
  { id: "basic_loop", desc: "Three baseline → advice → retake → compare loops, a keeper, a late RAW" },
  { id: "ingest_stress", desc: "Partial writes, duplicates, late RAW, missing EXIF" },
  { id: "stale_switch", desc: "Switch shots while the coach is still thinking" },
] as const;
