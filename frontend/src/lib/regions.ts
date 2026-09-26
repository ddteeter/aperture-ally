// Region drawing helpers: convert a drag on the displayed image into a normalized rect.
import type { Region } from "../api/types";

export const MAX_REGIONS = 3;
/** Minimum region size as a fraction of each image dimension. */
export const MIN_REGION_FRACTION = 0.02;

export interface Point {
  x: number;
  y: number;
}
export interface Size {
  width: number;
  height: number;
}
export interface NormRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const round4 = (v: number) => Math.round(v * 10000) / 10000;

/**
 * Convert a drag between two points (CSS pixels relative to the displayed image's top-left) into a
 * rect normalized to the image's natural size. The image is assumed to be displayed without
 * cropping (aspect preserved), so displayed→natural is a uniform scale per axis. Works for any drag
 * direction; clamps to 0..1; returns null if the rect is smaller than `minFraction` on either axis.
 */
export function normalizeDrag(
  start: Point,
  end: Point,
  displayed: Size,
  natural: Size = displayed,
  minFraction = MIN_REGION_FRACTION,
): NormRect | null {
  if (displayed.width <= 0 || displayed.height <= 0 || natural.width <= 0 || natural.height <= 0) return null;
  const sx = natural.width / displayed.width;
  const sy = natural.height / displayed.height;
  // to natural pixels, then normalize
  const nx0 = clamp01((Math.min(start.x, end.x) * sx) / natural.width);
  const nx1 = clamp01((Math.max(start.x, end.x) * sx) / natural.width);
  const ny0 = clamp01((Math.min(start.y, end.y) * sy) / natural.height);
  const ny1 = clamp01((Math.max(start.y, end.y) * sy) / natural.height);
  const w = nx1 - nx0;
  const h = ny1 - ny0;
  const eps = 1e-9; // tolerate float error (0.03 - 0.01 < 0.02)
  if (w < minFraction - eps || h < minFraction - eps) return null;
  const x = round4(nx0);
  const y = round4(ny0);
  // keep x+w <= 1 after rounding
  return { x, y, w: round4(Math.min(w, 1 - x)), h: round4(Math.min(h, 1 - y)) };
}

/** First free id among r1..r{MAX_REGIONS}, or null when full. */
export function nextRegionId(existing: Pick<Region, "id">[]): string | null {
  if (existing.length >= MAX_REGIONS) return null;
  const used = new Set(existing.map((r) => r.id));
  for (let i = 1; i <= MAX_REGIONS; i++) {
    if (!used.has(`r${i}`)) return `r${i}`;
  }
  return null;
}

/** Next criterion id c{n+1} that doesn't collide with existing ids (existing ids stay stable). */
export function nextCriterionId(existing: { id: string }[]): string {
  let max = 0;
  for (const c of existing) {
    const m = /^c(\d+)$/.exec(c.id);
    if (m) max = Math.max(max, Number(m[1]));
  }
  let n = max + 1;
  const used = new Set(existing.map((c) => c.id));
  while (used.has(`c${n}`)) n++;
  return `c${n}`;
}
