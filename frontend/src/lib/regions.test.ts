import { describe, expect, it } from "vitest";
import { addRegion, MAX_REGIONS, nextCriterionId, nextRegionId, normalizeDrag, removeRegion, renameRegion } from "./regions";

describe("normalizeDrag", () => {
  const displayed = { width: 800, height: 533.33 };
  const natural = { width: 2400, height: 1600 };

  it("normalizes a pixel rect on a scaled display to the natural image", () => {
    const r = normalizeDrag({ x: 80, y: 53.333 }, { x: 400, y: 266.665 }, displayed, natural)!;
    expect(r.x).toBeCloseTo(0.1, 3);
    expect(r.y).toBeCloseTo(0.1, 3);
    expect(r.w).toBeCloseTo(0.4, 3);
    expect(r.h).toBeCloseTo(0.4, 3);
  });

  it("gives the same result for any display size (scale-invariant)", () => {
    const a = normalizeDrag({ x: 100, y: 50 }, { x: 300, y: 150 }, { width: 1000, height: 500 }, { width: 4000, height: 2000 })!;
    const b = normalizeDrag({ x: 30, y: 15 }, { x: 90, y: 45 }, { width: 300, height: 150 }, { width: 4000, height: 2000 })!;
    expect(a).toEqual(b);
    expect(a).toEqual({ x: 0.1, y: 0.1, w: 0.2, h: 0.2 });
  });

  it("handles a reversed (bottom-right to top-left) drag", () => {
    const fwd = normalizeDrag({ x: 100, y: 100 }, { x: 300, y: 200 }, { width: 1000, height: 1000 });
    const rev = normalizeDrag({ x: 300, y: 200 }, { x: 100, y: 100 }, { width: 1000, height: 1000 });
    const mixed = normalizeDrag({ x: 300, y: 100 }, { x: 100, y: 200 }, { width: 1000, height: 1000 });
    expect(rev).toEqual(fwd);
    expect(mixed).toEqual(fwd);
    expect(fwd).toEqual({ x: 0.1, y: 0.1, w: 0.2, h: 0.1 });
  });

  it("clamps drags that leave the image to 0..1", () => {
    const r = normalizeDrag({ x: -50, y: -20 }, { x: 1200, y: 600 }, { width: 1000, height: 500 })!;
    expect(r).toEqual({ x: 0, y: 0, w: 1, h: 1 });
    const edge = normalizeDrag({ x: 900, y: 400 }, { x: 5000, y: 5000 }, { width: 1000, height: 500 })!;
    expect(edge.x + edge.w).toBeLessThanOrEqual(1);
    expect(edge.y + edge.h).toBeLessThanOrEqual(1);
    expect(edge).toEqual({ x: 0.9, y: 0.8, w: 0.1, h: 0.2 });
  });

  it("rejects rects below the minimum size (clicks and thin slivers)", () => {
    expect(normalizeDrag({ x: 10, y: 10 }, { x: 10, y: 10 }, { width: 1000, height: 1000 })).toBeNull();
    expect(normalizeDrag({ x: 10, y: 10 }, { x: 25, y: 400 }, { width: 1000, height: 1000 })).toBeNull(); // w=0.015
    expect(normalizeDrag({ x: 10, y: 10 }, { x: 30, y: 30 }, { width: 1000, height: 1000 })).toEqual({ x: 0.01, y: 0.01, w: 0.02, h: 0.02 });
    expect(normalizeDrag({ x: 10, y: 10 }, { x: 30, y: 30 }, { width: 1000, height: 1000 }, undefined, 0.05)).toBeNull();
  });

  it("returns null for a zero-size image", () => {
    expect(normalizeDrag({ x: 0, y: 0 }, { x: 10, y: 10 }, { width: 0, height: 0 })).toBeNull();
  });
});

describe("ids", () => {
  it("nextRegionId fills r1..r3 and stops at 3", () => {
    expect(nextRegionId([])).toBe("r1");
    expect(nextRegionId([{ id: "r1" }, { id: "r3" }])).toBe("r2");
    expect(nextRegionId([{ id: "r1" }, { id: "r2" }, { id: "r3" }])).toBeNull();
  });
  it("nextCriterionId never reuses an existing id", () => {
    expect(nextCriterionId([])).toBe("c1");
    expect(nextCriterionId([{ id: "c1" }, { id: "c3" }])).toBe("c4");
    expect(nextCriterionId([{ id: "custom" }])).toBe("c1");
  });
});

describe("addRegion / renameRegion / removeRegion", () => {
  const rect = { x: 0.1, y: 0.1, w: 0.2, h: 0.2 };
  it("adds up to three regions, then refuses", () => {
    let list = addRegion([], rect)!;
    expect(list).toEqual([{ id: "r1", label: "Region 1", ...rect }]);
    list = addRegion(list, rect)!;
    list = addRegion(list, rect)!;
    expect(list.map((r) => r.id)).toEqual(["r1", "r2", "r3"]);
    expect(list).toHaveLength(MAX_REGIONS);
    expect(addRegion(list, rect)).toBeNull();
  });
  it("reuses a freed id after a delete", () => {
    const three = addRegion(addRegion(addRegion([], rect)!, rect)!, rect)!;
    const two = removeRegion(three, "r2");
    expect(two.map((r) => r.id)).toEqual(["r1", "r3"]);
    expect(addRegion(two, rect)!.at(-1)!.id).toBe("r2");
  });
  it("renames in place and ignores blank names", () => {
    const list = addRegion([], rect)!;
    expect(renameRegion(list, "r1", "  Toe box logo ")[0].label).toBe("Toe box logo");
    expect(renameRegion(list, "r1", "   ")[0].label).toBe("Region 1");
  });
});
