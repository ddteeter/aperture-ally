import { describe, expect, it } from "vitest";
import {
  ago,
  captureMeta,
  coverageCounts,
  coverageCta,
  coverageHeadline,
  coverageMeta,
  healthRows,
  reorderPatches,
  revisionPhotos,
  seconds,
  setupChanges,
  shutter,
  watchFolderNote,
} from "./workflowsLogic";
import { covShot, makeCoverage, makeDiag, makeShot, makeState, setupRev } from "./workflows.testutil";
import { baselineCapture } from "../test/fixtures";

describe("coverage helpers", () => {
  const shots = [
    covShot("a", "A", "accepted", { resolved: true }),
    covShot("b", "B", "candidate"),
    covShot("c", "C", "needs_retake"),
    covShot("d", "D", "missing"),
    covShot("e", "E", "missing"),
  ];
  it("counts each state", () => {
    expect(coverageCounts(shots)).toEqual({ keepers: 1, candidates: 1, retakes: 1, missing: 2 });
  });
  it("headline says how many shots still need a keeper, or ready", () => {
    expect(coverageHeadline(makeCoverage(shots))).toBe("Not yet — 4 shots still missing");
    expect(coverageHeadline(makeCoverage([shots[0], shots[1]]))).toBe("Not yet — 1 shot still missing");
    expect(coverageHeadline(makeCoverage([shots[0]]))).toBe("Ready to export");
    expect(coverageHeadline(makeCoverage([]))).toBe("No shots yet");
  });
  it("CTA per state", () => {
    expect(coverageCta("missing")).toBe("Shoot this →");
    expect(coverageCta("needs_retake")).toBe("Retake →");
    expect(coverageCta("candidate")).toBe("Pick a keeper →");
    expect(coverageCta("accepted")).toBe("Change keeper →");
  });
  it("formats keeper meta from EXIF and attempts for other states", () => {
    expect(shutter(1 / 125)).toBe("1/125 s");
    expect(shutter(2)).toBe("2 s");
    expect(shutter(null)).toBeNull();
    const cap = { ...baselineCapture, exif: { exposure_time_s: 1 / 125, f_number: 5.6 } };
    expect(captureMeta(cap, 3)).toBe("#3 · 1/125 s · f/5.6");
    const keeper = covShot("a", "A", "accepted", {
      keeper: { capture_id: cap.id, capture_seq: 3 } as never,
    });
    expect(coverageMeta(keeper, [cap])).toBe("#3 · 1/125 s · f/5.6");
    expect(coverageMeta(covShot("d", "D", "missing"), [])).toBe("No photos yet");
    expect(coverageMeta(covShot("c", "C", "needs_retake", { captures: 4, latest_assessed_seq: 9 }), [])).toBe("4 attempts · last #9");
  });
});

describe("reorderPatches", () => {
  const shots = [makeShot("a", 0, "A"), makeShot("b", 1, "B"), makeShot("c", 2, "C")];
  it("swaps neighbours", () => {
    expect(reorderPatches(shots, "b", -1)).toEqual([
      { id: "b", ordinal: 0 },
      { id: "a", ordinal: 1 },
    ]);
  });
  it("does nothing past the ends", () => {
    expect(reorderPatches(shots, "a", -1)).toEqual([]);
    expect(reorderPatches(shots, "c", 1)).toEqual([]);
  });
  it("renumbers duplicate ordinals so the move sticks", () => {
    const dup = [makeShot("a", 0, "A"), makeShot("b", 0, "B"), makeShot("c", 0, "C")];
    expect(reorderPatches(dup, "a", 1)).toEqual([
      { id: "a", ordinal: 1 },
      { id: "c", ordinal: 2 },
    ]);
  });
});

describe("setup versions", () => {
  it("describes what changed", () => {
    expect(setupChanges(null, setupRev)).toBe("Session start");
    expect(setupChanges(setupRev, { ...setupRev })).toBe("No changes");
    expect(setupChanges(setupRev, { ...setupRev, light: "continuous" })).toBe("Light type → continuous");
    expect(
      setupChanges(setupRev, { ...setupRev, light: "flash", light_mobility: "fixed_sun_or_window", notes: "x" }),
    ).toBe("Light type → flash · Light position → fixed sun or window · +1 more");
  });
  it("formats the photo range", () => {
    expect(revisionPhotos({ capture_count: 7, first_seq: 9, last_seq: 15 })).toBe("photos #9–#15");
    expect(revisionPhotos({ capture_count: 1, first_seq: 4, last_seq: 4 })).toBe("photo #4");
    expect(revisionPhotos({ capture_count: 0, first_seq: null, last_seq: null })).toBe("no photos yet");
  });
});

describe("diagnostics helpers", () => {
  const now = new Date("2026-09-26T10:00:12Z").getTime();
  it("ago / seconds", () => {
    expect(ago("2026-09-26T10:00:00Z", now)).toBe("12 s");
    expect(ago(null, now)).toBeNull();
    expect(seconds(4100)).toBe("4.1 s");
    expect(seconds(null)).toBe("—");
  });
  it("maps state + doctor checks onto health rows", () => {
    const rows = healthRows(makeDiag(), makeState({ last_file_at: "2026-09-26T10:00:00Z" }), now);
    expect(rows.map((r) => r.label)).toEqual([
      "Watch folder: last file 12 s ago",
      "Network",
      "Transcription",
      "Speech out",
      "Microphone",
      "Budget",
    ]);
    expect(rows[0].ok).toBe(true);
    expect(rows[1].detail).toMatch(/mock provider/);
    expect(rows[4]).toMatchObject({ ok: null, detail: "default=None" });
    expect(rows[5]).toMatchObject({ ok: null, detail: "not reported" });
  });
  it("flags an unavailable paid provider and budget use", () => {
    const st = makeState({
      session: { ...makeState().session, assess_provider: "claude" },
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
    });
    const diag = makeDiag({
      providers: { configured: { mock: true, claude: true, openai: false, gemini: false }, health: { claude: { ok: false, at: "", error: "timeout" } } },
    });
    const rows = healthRows(diag, st, now);
    expect(rows[1]).toMatchObject({ ok: false, detail: "claude unavailable: timeout" });
    expect(rows[5]).toMatchObject({ ok: true, detail: "12 / 40 paid calls · ≈ $0.34" });
  });
  it("watch folder note validates the path", () => {
    expect(watchFolderNote("").tone).toBe("ok");
    expect(watchFolderNote("~/Pictures/Tether").tone).toBe("ok");
    expect(watchFolderNote("Pictures/x")).toMatchObject({ tone: "warn" });
  });
});
