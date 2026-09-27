// Filmstrip model: which captures are shown for a filter, the glyph badge for each, and its small tag.
import type { Capture, Keeper, PendingFile } from "../api/types";
import { CAPTURE_STATE, type StatusMeta, verdictMeta } from "../ui/status";
import { isAnalysing } from "./format";

export type FilmFilter = "all" | "shot" | "keepers";

export function activeKeeperIds(keepers: Keeper[]): Set<string> {
  return new Set(keepers.filter((k) => !k.revoked_at).map((k) => k.capture_id));
}

export function belongsToShot(c: Capture, shotId: string | null): boolean {
  return !!shotId && (c.shot_id === shotId || c.extra_shot_ids.includes(shotId));
}

/** Captures shown for a filter, oldest first (newest on the right). */
export function filmCaptures(captures: Capture[], filter: FilmFilter, activeShotId: string | null, keeperIds: Set<string>): Capture[] {
  return captures
    .filter((c) => (filter === "shot" ? belongsToShot(c, activeShotId) : filter === "keepers" ? keeperIds.has(c.id) : true))
    .sort((a, b) => a.seq - b.seq);
}

/** RAW-only with no usable preview: the one case where there is nothing to analyse. */
export function isRawOnlyNoPreview(c: Capture): boolean {
  return c.preview_source === "none" || (!c.jpeg_name && !!c.raw_name && c.processing_state === "failed" && !c.evidence.available);
}

/** The single glyph badge on a thumbnail: file problems first, then work in progress, then the verdict. */
export function captureBadge(c: Capture, isKeeper: boolean): StatusMeta {
  if (isRawOnlyNoPreview(c)) return CAPTURE_STATE.unsupported;
  if (c.processing_state === "failed" && c.latest_assessment?.status !== "failed") return CAPTURE_STATE.bad_file;
  if (isAnalysing(c)) return CAPTURE_STATE.analysing;
  if (isKeeper) return CAPTURE_STATE.keeper;
  if (c.latest_assessment?.status === "failed") return CAPTURE_STATE.failed;
  if (c.attribution_ambiguous) return CAPTURE_STATE.maybe_other_shot;
  const v = c.latest_assessment?.status === "completed" ? c.latest_assessment.result?.verdict : null;
  return v ? verdictMeta(v) : CAPTURE_STATE.no_verdict;
}

export interface FilmTag {
  text: string;
  label: string;
}

/** Small corner tag: late RAW attached, recovered after restart, or RAW-only (with an embedded preview). */
export function captureTag(c: Capture): FilmTag | null {
  if (c.pairing?.late_raw) return { text: "+RAW", label: "late RAW attached" };
  if (c.recovered) return { text: "↻", label: "recovered after restart" };
  if (c.preview_source === "raw_embedded" || c.preview_source === "raw_developed") return { text: "RAW", label: "RAW-only" };
  return null;
}

/** Watch-folder files not yet readable. "Still being written" never shows a percentage: we don't know it. */
export function pendingMeta(p: PendingFile): StatusMeta {
  return p.status === "failed" ? { ...CAPTURE_STATE.bad_file, word: "Couldn’t be read" } : CAPTURE_STATE.writing;
}

/** Next capture id when stepping with ← / →; stays put at the ends. */
export function stepCapture(list: Capture[], selectedId: string | null, dir: -1 | 1): string | null {
  if (list.length === 0) return null;
  const i = list.findIndex((c) => c.id === selectedId);
  if (i < 0) return (dir < 0 ? list[list.length - 1] : list[0]).id;
  const j = Math.min(list.length - 1, Math.max(0, i + dir));
  return list[j].id;
}
