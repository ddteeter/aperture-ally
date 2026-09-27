// Brightness inspector model: marked regions first, whole frame last (design system "Teaching histogram").
import type { Capture, InsightSeverity, Measurements, ScopeInsight, Shot } from "../api/types";

export const WHOLE = "all";

export interface ScopeRow {
  /** Region id, or "all" for the whole frame. */
  key: string;
  /** 1-based index of the region on the shot (matches the label on the photo); null for the whole frame. */
  index: number | null;
  name: string;
  insight: ScopeInsight | null;
  bins: number[] | null;
  clipHigh: number;
  clipLow: number;
  meta: string;
}

/** Same rounding as the backend reading: one decimal under 10 %. */
export function clipPct(f: number): string {
  const p = f * 100;
  return `${p < 10 ? p.toFixed(1) : p.toFixed(0)}%`;
}

/** Relative sharpness only, never an absolute score. */
export function sharpnessText(pctChange: number): string {
  const r = Math.round(pctChange);
  if (Math.abs(r) < 5) return `about as sharp (${r >= 0 ? "+" : "−"}${Math.abs(r)}%)`;
  return r > 0 ? `+${r}% sharper` : `${Math.abs(r)}% less sharp`;
}

export function measurementsOf(c: Capture): Measurements | null {
  const la = c.latest_assessment;
  return (la?.status === "completed" && la.measurements) || c.evidence.measurements || null;
}

export function scopeRows(capture: Capture, shot: Shot | null): ScopeRow[] {
  const m = measurementsOf(capture);
  const ins = capture.histogram_insights;
  const shotRegions = shot?.sharp_regions ?? [];
  const deltas = capture.comparison_metrics?.regions ?? [];
  const rows: ScopeRow[] = [];
  const seen = new Set<string>();

  const regionIds = [
    ...shotRegions.map((r) => r.id),
    ...(ins?.regions.map((r) => r.region_id ?? "") ?? []).filter(Boolean),
    ...Object.keys(m?.regions ?? {}),
  ];
  for (const rid of regionIds) {
    if (seen.has(rid)) continue;
    seen.add(rid);
    const idx = shotRegions.findIndex((r) => r.id === rid);
    const insight = ins?.regions.find((r) => r.region_id === rid) ?? null;
    const rm = m?.regions[rid];
    const label = shotRegions[idx]?.label ?? insight?.scope ?? rid;
    const clipHigh = insight?.highlight_clip ?? rm?.highlight_clip_fraction ?? 0;
    const clipLow = insight?.shadow_clip ?? rm?.shadow_clip_fraction ?? 0;
    const delta = deltas.find((d) => d.scope === rid);
    const parts: string[] = [];
    if (delta?.sharpness_change_pct != null) parts.push(sharpnessText(delta.sharpness_change_pct));
    if (insight || rm) parts.push(`${clipPct(clipHigh)} white`);
    else parts.push("measured on the next photo");
    rows.push({
      key: rid,
      index: idx >= 0 ? idx + 1 : null,
      name: idx >= 0 ? `${idx + 1} ${label}` : label,
      insight,
      bins: rm?.histogram ?? null,
      clipHigh,
      clipLow,
      meta: parts.join(" · "),
    });
  }
  const g = m?.global;
  const overall = ins?.overall ?? null;
  const hi = overall?.highlight_clip ?? g?.highlight_clip_fraction ?? 0;
  rows.push({
    key: WHOLE,
    index: null,
    name: "Whole frame",
    insight: overall,
    bins: g?.histogram ?? null,
    clipHigh: hi,
    clipLow: overall?.shadow_clip ?? g?.shadow_clip_fraction ?? 0,
    meta: g || overall ? `${clipPct(hi)} pure white` : "not measured yet",
  });
  return rows;
}

const RANK: Record<InsightSeverity, number> = { problem: 3, warn: 2, info: 1, ok: 0 };

/** Start on the worst marked region (that's where detail is lost); else the first region; else the frame. */
export function defaultScope(rows: ScopeRow[]): string {
  const regions = rows.filter((r) => r.key !== WHOLE && r.insight);
  if (regions.length === 0) return WHOLE;
  const worst = regions.reduce((a, r) => (RANK[r.insight!.severity] > RANK[a.insight!.severity] ? r : a), regions[0]);
  return worst.key;
}

/** Context line under the headline: the most important finding's explanation. */
export function contextLine(s: ScopeInsight | null): string {
  if (!s) return "";
  const f = s.findings.find((x) => x.severity === s.severity) ?? s.findings[0];
  if (!f) return s.shape;
  return f.headline === s.headline ? f.detail : `${f.headline}. ${f.detail}`;
}
