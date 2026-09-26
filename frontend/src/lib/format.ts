import type { Capture, Shot } from "../api/types";

export function pct(fraction: number | null | undefined, digits = 1): string {
  if (fraction == null || Number.isNaN(fraction)) return "n/a";
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return "n/a";
  return v.toFixed(digits);
}

export function ms(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "n/a";
  return `${Math.round(v)} ms`;
}

export function humanize(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(/_/g, " ");
}

export function shortTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function shotTitle(shots: Shot[], id: string | null | undefined): string {
  if (!id) return "no shot";
  return shots.find((s) => s.id === id)?.title ?? "unknown shot";
}

export function seqOf(captures: Capture[], id: string | null | undefined): number | null {
  if (!id) return null;
  return captures.find((c) => c.id === id)?.seq ?? null;
}

export function splitList(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

export function isAnalysing(c: Capture): boolean {
  const st = c.latest_assessment?.status;
  return c.processing_state === "analyzing" || st === "running" || st === "queued";
}
