// Pure view-model helpers for the coach panel (unit-tested in model.test.ts).
import type {
  Assessment,
  AssessmentResult,
  Capture,
  ComparisonMetrics,
  CriterionResult,
  Exif,
  ExposureNote,
  ScopeDelta,
  Session,
  SessionUsage,
  ZoneName,
} from "../../api/types";
import { CLIP_SHOW } from "../../ui/Histogram";

export type Tone = "ok" | "ret" | "unc" | "acc" | "t1" | "t3";

export const TONE_COLOR: Record<Tone, string> = {
  ok: "var(--ok)",
  ret: "var(--ret)",
  unc: "var(--unc)",
  acc: "var(--acc)",
  t1: "var(--t1)",
  t3: "var(--t3)",
};

const PROVIDERS: Record<string, string> = { claude: "Claude", openai: "OpenAI", gemini: "Gemini", mock: "Mock" };
export function providerLabel(p: string | null | undefined): string {
  if (!p) return "the coach";
  return PROVIDERS[p] ?? p;
}

/** "4.2 s" from milliseconds. */
export function seconds(msv: number | null | undefined): string | null {
  if (msv == null || Number.isNaN(msv) || msv < 0) return null;
  return `${(msv / 1000).toFixed(1)} s`;
}

export function msBetween(a: string | null | undefined, b: string | null | undefined): number | null {
  if (!a || !b) return null;
  const d = new Date(b).getTime() - new Date(a).getTime();
  return Number.isFinite(d) && d >= 0 ? d : null;
}

export function shutterLabel(s: number | null | undefined): string | null {
  if (s == null || !(s > 0)) return null;
  if (s >= 0.5) return `${Number.isInteger(s) ? s : s.toFixed(1)} s`;
  return `1/${Math.round(1 / s)} s`;
}

export interface ExifCell {
  k: string;
  v: string;
  missing: boolean;
}
export function exifCells(exif: Exif | null | undefined): ExifCell[] {
  const e = exif ?? {};
  const cell = (k: string, v: string | null): ExifCell => ({ k, v: v ?? "not in EXIF", missing: v == null });
  return [
    cell("Shutter", shutterLabel(e.exposure_time_s)),
    cell("Aperture", e.f_number ? `f/${fmtF(e.f_number)}` : null),
    cell("ISO", e.iso ? String(e.iso) : null),
    cell("Lens", e.lens || null),
  ];
}
const fmtF = (f: number) => (Number.isInteger(f) ? String(f) : f.toFixed(1));

export function exifLine(exif: Exif | null | undefined): string {
  return exifCells(exif)
    .filter((c) => !c.missing && c.k !== "Lens")
    .map((c) => (c.k === "ISO" ? `ISO ${c.v}` : c.v))
    .join(" · ");
}

export function criteriaSummary(results: CriterionResult[]): string {
  const n = (r: string) => results.filter((x) => x.result === r).length;
  const parts: string[] = [];
  if (n("pass")) parts.push(`${n("pass")} pass`);
  if (n("uncertain")) parts.push(`${n("uncertain")} unsure`);
  if (n("fail")) parts.push(`${n("fail")} fail`);
  return parts.join(" · ");
}

export type StartingPoint = { kind: "value"; value: string; detail: string } | { kind: "none"; reason: string };

/** The STARTING POINT line under DO THIS: a rounded exposure, or why it wasn't calculated. */
export function startingPoint(note: ExposureNote | null | undefined): StartingPoint | null {
  if (!note) return null;
  if (!note.applicable) {
    const reason = note.reasons.join("; ") || note.note || "not enough information";
    return { kind: "none", reason };
  }
  const f = note.new_f_number ?? note.old?.f_number ?? null;
  const iso = note.new_iso ?? note.old?.iso ?? null;
  const shutter = note.rounded_label ?? shutterLabel(note.rounded_duration_s);
  if (!shutter) return note.note ? { kind: "value", value: note.note, detail: "" } : null;
  const value = f ? `${shutter} at f/${fmtF(f)}` : shutter;
  const detail = [iso ? `ISO ${iso}` : null, note.note].filter(Boolean).join(" · ");
  return { kind: "value", value, detail };
}

export function tokensLabel(usage: Assessment["usage"]): string | null {
  if (!usage) return null;
  const t = (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0);
  if (!t) return null;
  return t >= 1000 ? `${(t / 1000).toFixed(1)}k tokens` : `${t} tokens`;
}

/** Muted model line: provider · served model · tokens · cost. */
/** "Usable" with nothing to change, "Usable, but…" (fine to keep, one optional change), or the verdict's own word. */
export function verdictKind(r: AssessmentResult): "usable" | "usable_but" | "retake" | "uncertain" {
  if (r.verdict === "usable_candidate") return r.primary_action ? "usable_but" : "usable";
  return r.verdict === "needs_retake" ? "retake" : "uncertain";
}

export function modelLine(a: Assessment): string {
  const cost =
    a.cost_estimate_usd != null ? `$${a.cost_estimate_usd.toFixed(3)}` : a.provider === "mock" ? "$0 (mock)" : "cost n/a";
  return [providerLabel(a.provider), a.model_resolved ?? a.model_requested ?? "model n/a", tokensLabel(a.usage), cost]
    .filter(Boolean)
    .join(" · ");
}

const SEVERITY_RANK: Record<string, number> = { blocking: 3, major: 2, minor: 1, info: 0 };

/** Where "Show me on the photo" should point: the most severe observation's region and a zone guessed from its text. */
export function pickShowZone(r: AssessmentResult): { regionId: string | null; zone: ZoneName } | null {
  if (!r.observations.length) return null;
  const obs = [...r.observations].sort((a, b) => (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0));
  const zoneOf = (t: string): ZoneName | null => {
    const s = t.toLowerCase();
    if (/(pure black|crushed|shadow clip|blocked)/.test(s)) return "clip_low";
    if (/(clip|pure white|blown|glare|specular)/.test(s)) return "clip_high";
    if (/shadow/.test(s)) return "shadows";
    if (/highlight/.test(s)) return "highlights";
    return null;
  };
  const withZone = obs.find((o) => zoneOf(o.observation));
  const pick = withZone ?? obs.find((o) => o.region_id) ?? obs[0];
  return { regionId: pick.region_id, zone: zoneOf(pick.observation) ?? "clip_high" };
}

// --- comparison ------------------------------------------------------------------------------

export interface ChangeRow {
  glyph: string;
  tone: Tone;
  label: string;
  value: string;
}

const clipPct = (f: number) => `${(f * 100).toFixed(1)}%`;
const SAME_SHARP = 10;

export function sharpText(pct: number): string {
  const r = Math.round(pct);
  if (Math.abs(pct) < SAME_SHARP) return `about as sharp (${r >= 0 ? "+" : "−"}${Math.abs(r)}%)`;
  return pct > 0 ? `+${r}% sharper` : `${Math.abs(r)}% less sharp`;
}

export function evLabel(ev: number): string {
  const v = Math.abs(ev).toFixed(1);
  return `≈ ${ev > 0 ? "+" : ev < 0 ? "−" : "±"}${v} EV`;
}

function clipRow(kind: "white" | "black", where: string, before: number, after: number): ChangeRow | null {
  if (Math.max(before, after) < CLIP_SHOW || Math.abs(after - before) < 0.001) return null;
  const better = after < before;
  return {
    glyph: better ? "▲" : "▼",
    tone: better ? "ok" : "ret",
    label: `Pure ${kind} ${where}`,
    value: `${clipPct(before)} → ${clipPct(after)}`,
  };
}

function sharpRow(d: ScopeDelta): ChangeRow | null {
  const p = d.sharpness_change_pct;
  if (p == null) return null;
  const same = Math.abs(p) < SAME_SHARP;
  return { glyph: same ? "◆" : p > 0 ? "▲" : "▼", tone: same ? "unc" : p > 0 ? "ok" : "ret", label: d.label, value: sharpText(p) };
}

export function brightnessRow(g: ScopeDelta): ChangeRow {
  const diff = g.mean_after - g.mean_before;
  const m = `mean ${Math.round(g.mean_before)} → ${Math.round(g.mean_after)} of 255`;
  if (Math.abs(diff) < 2) return { glyph: "◆", tone: "unc", label: "Overall brightness about the same", value: m };
  return { glyph: "◆", tone: "unc", label: diff > 0 ? "Overall brighter" : "Overall darker", value: m };
}

/** WHAT CHANGED rows from measured before/after numbers. */
export function whatChanged(m: ComparisonMetrics): ChangeRow[] {
  const rows: ChangeRow[] = [];
  for (const d of m.regions) {
    const where = `on the ${d.label}`;
    const w = clipRow("white", where, d.highlight_clip_before, d.highlight_clip_after);
    const b = clipRow("black", where, d.shadow_clip_before, d.shadow_clip_after);
    const s = sharpRow(d);
    for (const r of [w, b, s]) if (r) rows.push(r);
  }
  if (m.global) {
    if (!rows.some((r) => r.label.startsWith("Pure"))) {
      const w = clipRow("white", "in the frame", m.global.highlight_clip_before, m.global.highlight_clip_after);
      const b = clipRow("black", "in the frame", m.global.shadow_clip_before, m.global.shadow_clip_after);
      for (const r of [w, b]) if (r) rows.push(r);
    }
    rows.push(brightnessRow(m.global));
  }
  return rows;
}

export interface RegionPairView {
  glyph: string;
  word: string;
  tone: Tone;
  sentence: string;
}

/** Per-region before/after verdict for the region pair rows. */
export function regionPair(d: ScopeDelta, comparable: boolean): RegionPairView {
  if (!comparable) {
    return { glyph: "?", word: "Can’t match", tone: "t3", sentence: "The framing changed too much to line this region up." };
  }
  let score = 0;
  const parts: string[] = [];
  const p = d.sharpness_change_pct;
  if (p != null) {
    if (p >= SAME_SHARP) score++;
    if (p <= -SAME_SHARP) score--;
    const t = sharpText(p);
    parts.push(t.charAt(0).toUpperCase() + t.slice(1) + ".");
  }
  const dc = d.highlight_clip_after - d.highlight_clip_before;
  if (Math.max(d.highlight_clip_before, d.highlight_clip_after) >= CLIP_SHOW && Math.abs(dc) >= 0.001) {
    score += dc < 0 ? 1 : -1;
    parts.push(`Pure white ${clipPct(d.highlight_clip_before)} → ${clipPct(d.highlight_clip_after)}.`);
  }
  const dm = d.mean_after - d.mean_before;
  parts.push(Math.abs(dm) < 2 ? "Brightness unchanged." : `${dm > 0 ? "Brighter" : "Darker"}, mean ${Math.round(d.mean_before)} → ${Math.round(d.mean_after)}.`);
  const sentence = parts.join(" ");
  if (score > 0) return { glyph: "▲", word: "Better", tone: "ok", sentence };
  if (score < 0) return { glyph: "▼", word: "Worse", tone: "ret", sentence };
  return { glyph: "◆", word: "Same", tone: "unc", sentence };
}

// --- analysing -------------------------------------------------------------------------------

export type StepState = "done" | "active" | "waiting";
export interface Step {
  label: string;
  state: StepState;
  time: string | null;
}

export function analysisSteps(c: Capture, la: Assessment | null, now: number, criteriaCount: number): Step[] {
  const provider = providerLabel(la?.provider);
  const measured = c.evidence?.available ?? false;
  const running = la?.status === "running";
  const started = la?.created_at ? new Date(la.created_at).getTime() : null;
  const asking = criteriaCount ? `${provider} reviewing against ${criteriaCount} criteria` : `Asking ${provider}`;
  return [
    { label: "File received", state: "done", time: seconds(msBetween(c.detected_at, c.ready_at)) },
    { label: "Measured locally", state: measured ? "done" : "active", time: seconds(la?.timings?.evidence_ms) },
    {
      label: la?.status === "queued" ? `Waiting for ${provider}` : asking,
      state: measured ? "active" : "waiting",
      time: running && started ? seconds(Math.max(0, now - started)) : null,
    },
    { label: "Speak verdict", state: "waiting", time: null },
  ];
}

// --- paused ----------------------------------------------------------------------------------

/** "Raise cap to N": +20 calls when the call cap was hit, else +$1 on the spend cap. */
export function raiseCap(
  session: Session,
  usage: SessionUsage | undefined,
): { label: string; patch: { max_model_calls?: number; budget_usd?: number } } | null {
  if (!usage?.exceeded) return null;
  const calls = usage.max_model_calls ?? session.max_model_calls;
  if (calls != null && usage.capped_calls >= calls) {
    return { label: `Raise cap to ${calls + 20}`, patch: { max_model_calls: calls + 20 } };
  }
  const budget = usage.budget_usd ?? session.budget_usd;
  if (budget != null) {
    const next = Math.round((budget + 1) * 100) / 100;
    return { label: `Raise cap to $${next.toFixed(2)}`, patch: { budget_usd: next } };
  }
  return null;
}
