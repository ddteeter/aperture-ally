import { describe, expect, it } from "vitest";
import type { ComparisonMetrics, ScopeDelta } from "../../api/types";
import { assessment, makeCapture, sessionState } from "../../test/fixtures";
import {
  analysisSteps,
  criteriaSummary,
  evLabel,
  exifCells,
  modelLine,
  pickShowZone,
  raiseCap,
  regionPair,
  sharpText,
  startingPoint,
  whatChanged,
} from "./model";

const delta = (extra: Partial<ScopeDelta> = {}): ScopeDelta => ({
  scope: "r1",
  label: "logo",
  sharpness_change_pct: null,
  mean_before: 120,
  mean_after: 120,
  highlight_clip_before: 0,
  highlight_clip_after: 0,
  shadow_clip_before: 0,
  shadow_clip_after: 0,
  histogram_before: null,
  histogram_after: null,
  ...extra,
});

describe("coach model", () => {
  it("formats relative sharpness without absolute numbers", () => {
    expect(sharpText(36.2)).toBe("+36% sharper");
    expect(sharpText(-22)).toBe("22% less sharp");
    expect(sharpText(2)).toBe("about as sharp (+2%)");
    expect(sharpText(-3)).toBe("about as sharp (−3%)");
  });

  it("builds WHAT CHANGED rows from comparison metrics", () => {
    const m: ComparisonMetrics = {
      baseline_capture_id: "cap-1",
      baseline_seq: 12,
      framing: { score: 0.94, comparable: true },
      ev_delta: null,
      ev_note: null,
      regions: [
        delta({ label: "trim", highlight_clip_before: 0.031, highlight_clip_after: 0.004 }),
        delta({ label: "logo", sharpness_change_pct: 36 }),
      ],
      global: delta({ scope: "global", label: "Whole frame", mean_before: 124, mean_after: 118 }),
    };
    const rows = whatChanged(m);
    expect(rows).toEqual([
      { glyph: "▲", tone: "ok", label: "Pure white on the trim", value: "3.1% → 0.4%" },
      { glyph: "▲", tone: "ok", label: "logo", value: "+36% sharper" },
      { glyph: "◆", tone: "unc", label: "Overall darker", value: "mean 124 → 118 of 255" },
    ]);
  });

  it("only labels EV with a sign and one decimal", () => {
    expect(evLabel(-0.4)).toBe("≈ −0.4 EV");
    expect(evLabel(0.5)).toBe("≈ +0.5 EV");
  });

  it("judges a region pair, or refuses when framing isn't comparable", () => {
    expect(regionPair(delta({ sharpness_change_pct: 36 }), true)).toMatchObject({ word: "Better", glyph: "▲" });
    expect(regionPair(delta({ sharpness_change_pct: -22 }), true)).toMatchObject({ word: "Worse" });
    expect(regionPair(delta({ sharpness_change_pct: 2 }), true)).toMatchObject({ word: "Same" });
    expect(regionPair(delta({ sharpness_change_pct: 40 }), false)).toMatchObject({ word: "Can’t match", glyph: "?" });
  });

  it("gives a starting point or the reason it wasn't calculated", () => {
    expect(startingPoint({ applicable: false, reasons: ["light is flash"], note: null })).toEqual({ kind: "none", reason: "light is flash" });
    expect(
      startingPoint({ applicable: true, reasons: [], note: "tripod holds it", rounded_label: "1/15 s", new_f_number: 8, new_iso: 200 }),
    ).toEqual({ kind: "value", value: "1/15 s at f/8", detail: "ISO 200 · tripod holds it" });
    expect(startingPoint(null)).toBeNull();
  });

  it("marks missing EXIF", () => {
    const cells = exifCells({ exposure_time_s: 1 / 125, f_number: 5.6, iso: 200 });
    expect(cells.map((c) => c.v)).toEqual(["1/125 s", "f/5.6", "200", "not in EXIF"]);
    expect(cells[3].missing).toBe(true);
  });

  it("summarises criteria and the model line (served model, tokens, cost)", () => {
    expect(criteriaSummary([
      { criterion_id: "a", result: "pass", evidence: "" },
      { criterion_id: "b", result: "uncertain", evidence: "" },
      { criterion_id: "c", result: "fail", evidence: "" },
    ])).toBe("1 pass · 1 unsure · 1 fail");
    const a = assessment({ provider: "claude", model_requested: "claude-x", model_resolved: "claude-x-2", usage: { input_tokens: 1800, output_tokens: 300 }, cost_estimate_usd: 0.028 });
    expect(modelLine(a)).toBe("Claude · claude-x-2 · 2.1k tokens · $0.028");
  });

  it("points 'show me' at the most severe clipping observation", () => {
    const r = assessment().result!;
    const pick = pickShowZone({
      ...r,
      observations: [
        { region_id: "r1", observation: "Mesh is sharp.", evidence_source: "measurement", severity: "info" },
        { region_id: "r3", observation: "3.1% of the trim is clipped to pure white.", evidence_source: "measurement", severity: "major" },
      ],
    });
    expect(pick).toEqual({ regionId: "r3", zone: "clip_high" });
  });

  it("lists analysis steps with timings", () => {
    const c = makeCapture("c", 12, { detected_at: "2026-09-26T10:00:00.000Z", ready_at: "2026-09-26T10:00:00.800Z" });
    const la = assessment({ status: "running", result: null, provider: "claude", created_at: "2026-09-26T10:00:01.000Z", timings: { evidence_ms: 300 } });
    const steps = analysisSteps(c, la, new Date("2026-09-26T10:00:03.100Z").getTime(), 3);
    expect(steps.map((s) => [s.label, s.state, s.time])).toEqual([
      ["File received", "done", "0.8 s"],
      ["Measured locally", "done", "0.3 s"],
      ["Claude reviewing against 3 criteria", "active", "2.1 s"],
      ["Speak verdict", "waiting", null],
    ]);
  });

  it("raises whichever cap was hit", () => {
    const st = sessionState();
    expect(raiseCap(st.session, st.usage)).toBeNull();
    expect(raiseCap(st.session, { ...st.usage!, exceeded: true, capped_calls: 40 })).toEqual({ label: "Raise cap to 60", patch: { max_model_calls: 60 } });
    expect(
      raiseCap({ ...st.session, max_model_calls: null }, { ...st.usage!, max_model_calls: null, exceeded: true, budget_usd: 2 }),
    ).toEqual({ label: "Raise cap to $3.00", patch: { budget_usd: 3 } });
  });
});
