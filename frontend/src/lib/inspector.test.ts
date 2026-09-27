import { describe, expect, it } from "vitest";
import type { HistogramInsights, Measurements, ScopeInsight } from "../api/types";
import { makeCapture, shot } from "../test/fixtures";
import { clipPct, contextLine, defaultScope, scopeRows, sharpnessText, WHOLE } from "./inspector";

const stats = (hi: number) => ({
  mean_luminance: 120, p01_luminance: 5, p99_luminance: 250, highlight_clip_fraction: hi, shadow_clip_fraction: 0,
  channel_highlight_clip: {}, channel_shadow_clip: {}, laplacian_var: 900, tenengrad_mean: 1, gradient_p90: 1,
});
const measurements: Measurements = {
  image: { width: 2400, height: 1600, orientation_tag: null, icc_profile: null, color_assumption: "sRGB" },
  global: { ...stats(0.009), histogram: Array(64).fill(1) },
  regions: { r1: { ...stats(0.031), rect: [0, 0, 1, 1], px_size: [10, 10], histogram: Array(64).fill(2) } },
  notes: {},
  caveats: [],
};
const insight = (scope: string, severity: ScopeInsight["severity"], extra: Partial<ScopeInsight> = {}): ScopeInsight => ({
  scope, headline: `${scope} headline`, shape: "Mostly mid-tones", severity, zones: {}, highlight_clip: 0.031, shadow_clip: 0,
  findings: [{ scope, severity, zone: "clip_high", headline: `${scope} headline`, detail: "Detail is gone there." }], ...extra,
});
const insights: HistogramInsights = {
  summary: "s",
  regions: [insight("forefoot mesh", "problem", { region_id: "r1" })],
  overall: insight("whole frame", "info", { highlight_clip: 0.009 }),
  how_to_read: ["Left to right is dark to bright."],
  caveat: "Measured on the processed JPEG, not the RAW file.",
};

describe("scopeRows", () => {
  it("lists marked regions first (numbered like the photo labels), whole frame last", () => {
    const c = makeCapture("c", 1, { evidence: { available: true, width: 2400, height: 1600, crops: [], measurements }, histogram_insights: insights });
    const rows = scopeRows(c, shot);
    expect(rows.map((r) => r.key)).toEqual(["r1", WHOLE]);
    expect(rows[0].name).toBe("1 forefoot mesh");
    expect(rows[0].meta).toBe("3.1% white");
    expect(rows[0].bins).toHaveLength(64);
    expect(rows[1].name).toBe("Whole frame");
    expect(rows[1].meta).toBe("0.9% pure white");
  });

  it("never shows an absolute sharpness number, only the relative change", () => {
    const c = makeCapture("c", 1, {
      evidence: { available: true, width: 2400, height: 1600, crops: [], measurements },
      histogram_insights: insights,
      comparison_metrics: {
        baseline_capture_id: "b", baseline_seq: 1, framing: null, ev_delta: null, ev_note: null, global: null,
        regions: [{ scope: "r1", label: "forefoot mesh", sharpness_change_pct: 36.2, mean_before: 1, mean_after: 1, highlight_clip_before: 0, highlight_clip_after: 0, shadow_clip_before: 0, shadow_clip_after: 0, histogram_before: null, histogram_after: null }],
      },
    });
    const meta = scopeRows(c, shot)[0].meta;
    expect(meta).toContain("+36% sharper");
    expect(meta).not.toMatch(/900|sharp \d/);
  });

  it("keeps a newly drawn region that hasn't been measured yet", () => {
    const withNew = { ...shot, sharp_regions: [...shot.sharp_regions, { id: "r2", label: "heel", x: 0, y: 0, w: 0.1, h: 0.1 }] };
    const rows = scopeRows(makeCapture("c", 1, { evidence: { available: true, width: 1, height: 1, crops: [], measurements } }), withNew);
    const r2 = rows.find((r) => r.key === "r2")!;
    expect(r2.name).toBe("2 heel");
    expect(r2.meta).toBe("measured on the next photo");
    expect(r2.bins).toBeNull();
  });
});

describe("defaultScope", () => {
  it("starts on the worst marked region, else the whole frame", () => {
    const c = makeCapture("c", 1, { evidence: { available: true, width: 1, height: 1, crops: [], measurements }, histogram_insights: insights });
    expect(defaultScope(scopeRows(c, shot))).toBe("r1");
    expect(defaultScope(scopeRows(makeCapture("d", 2), { ...shot, sharp_regions: [] }))).toBe(WHOLE);
  });
});

describe("text helpers", () => {
  it("formats relative sharpness and clip percentages", () => {
    expect(sharpnessText(36)).toBe("+36% sharper");
    expect(sharpnessText(-22.4)).toBe("22% less sharp");
    expect(sharpnessText(2)).toBe("about as sharp (+2%)");
    expect(clipPct(0.031)).toBe("3.1%");
    expect(clipPct(0.25)).toBe("25%");
  });
  it("builds the context line from the leading finding", () => {
    expect(contextLine(insights.regions[0])).toBe("Detail is gone there.");
    expect(contextLine(null)).toBe("");
  });
});
