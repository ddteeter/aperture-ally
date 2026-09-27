import { describe, expect, it } from "vitest";
import { assessment, makeCapture, shot } from "../test/fixtures";
import type { Keeper } from "../api/types";
import { activeKeeperIds, captureBadge, captureTag, filmCaptures, pendingMeta, stepCapture } from "./filmstrip";

const keeper = (capture_id: string, revoked_at: string | null = null): Keeper => ({
  id: `k-${capture_id}`,
  session_id: "s1",
  shot_id: shot.id,
  capture_id,
  stored_path: null,
  sha256: null,
  notes: null,
  criterion_notes: {},
  source: "ui",
  accepted_at: "2026-09-26T10:00:00Z",
  revoked_at,
});

describe("filmCaptures", () => {
  const a = makeCapture("a", 3);
  const b = makeCapture("b", 1, { shot_id: "other" });
  const c = makeCapture("c", 2, { shot_id: "other", extra_shot_ids: [shot.id] });
  const keepers = activeKeeperIds([keeper("b"), keeper("a", "2026-09-26T11:00:00Z")]);

  it("shows everything oldest first for All", () => {
    expect(filmCaptures([a, b, c], "all", shot.id, keepers).map((x) => x.seq)).toEqual([1, 2, 3]);
  });
  it("This shot includes photos linked to the shot as extras", () => {
    expect(filmCaptures([a, b, c], "shot", shot.id, keepers).map((x) => x.id)).toEqual(["c", "a"]);
    expect(filmCaptures([a, b, c], "shot", null, keepers)).toEqual([]);
  });
  it("Keepers ignores revoked keepers", () => {
    expect(filmCaptures([a, b, c], "keepers", shot.id, keepers).map((x) => x.id)).toEqual(["b"]);
  });
});

describe("captureBadge", () => {
  it("uses the verdict glyph and word", () => {
    const c = makeCapture("a", 1, { latest_assessment: assessment({ result: { ...assessment().result!, verdict: "needs_retake" } }) });
    expect(captureBadge(c, false)).toMatchObject({ glyph: "↺", word: "Needs retake" });
  });
  it("marks keepers, analysing, AI failures and unsure shot attribution", () => {
    expect(captureBadge(makeCapture("a", 1, { latest_assessment: assessment() }), true).glyph).toBe("★");
    expect(captureBadge(makeCapture("a", 1, { processing_state: "analyzing" }), false).word).toBe("Analysing");
    expect(captureBadge(makeCapture("a", 1, { latest_assessment: assessment({ status: "failed", result: null }) }), false).glyph).toBe("!");
    expect(captureBadge(makeCapture("a", 1, { attribution_ambiguous: true }), false).word).toBe("Might belong to previous shot");
    expect(captureBadge(makeCapture("a", 1), false).word).toBe("No verdict");
  });
  it("shows RAW-only only when there is no usable preview, otherwise a bad file", () => {
    const rawOnly = makeCapture("a", 1, { preview_source: "none", processing_state: "failed", jpeg_name: null, raw_name: "P1.ORF" });
    expect(captureBadge(rawOnly, false).word).toBe("RAW-only · no preview");
    const bad = makeCapture("b", 2, { processing_state: "failed", error: "truncated JPEG" });
    expect(captureBadge(bad, false).word).toBe("Bad file");
    const rawWithPreview = makeCapture("c", 3, { preview_source: "raw_embedded", jpeg_name: null, raw_name: "P3.ORF" });
    expect(captureBadge(rawWithPreview, false).word).not.toMatch(/RAW-only/);
  });
});

describe("captureTag", () => {
  it("tags late RAW, recovered and RAW-only captures", () => {
    expect(captureTag(makeCapture("a", 1, { pairing: { late_raw: true } }))?.text).toBe("+RAW");
    expect(captureTag(makeCapture("a", 1, { recovered: true }))?.text).toBe("↻");
    expect(captureTag(makeCapture("a", 1, { preview_source: "raw_embedded" }))?.text).toBe("RAW");
    expect(captureTag(makeCapture("a", 1))).toBeNull();
  });
});

describe("pendingMeta", () => {
  it("says still being written without any percentage", () => {
    const m = pendingMeta({ key: "k", name: "P1.JPG", status: "stabilizing", note: null });
    expect(m.word).toBe("Still being written");
    expect(m.word).not.toMatch(/%/);
    expect(pendingMeta({ key: "k", name: "P1.JPG", status: "failed", note: "x" }).glyph).toBe("⚠");
  });
});

describe("stepCapture", () => {
  const list = [makeCapture("a", 1), makeCapture("b", 2), makeCapture("c", 3)];
  it("moves one step and stops at the ends", () => {
    expect(stepCapture(list, "b", -1)).toBe("a");
    expect(stepCapture(list, "b", 1)).toBe("c");
    expect(stepCapture(list, "c", 1)).toBe("c");
    expect(stepCapture(list, "a", -1)).toBe("a");
  });
  it("enters the list from the right end when nothing visible is selected", () => {
    expect(stepCapture(list, "zzz", -1)).toBe("c");
    expect(stepCapture([], "a", 1)).toBeNull();
  });
});
