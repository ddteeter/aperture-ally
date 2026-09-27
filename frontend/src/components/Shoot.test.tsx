import { act, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Region, SessionState } from "../api/types";
import { AppContext, type AppCtx } from "../AppContext";
import { makeCtx, renderWithCtx } from "../test/ctx";
import { assessment, makeCapture, sessionState, shot } from "../test/fixtures";
import { Filmstrip } from "./Filmstrip";
import { HonestyBand, netStatus } from "./Header";
import { RegionEditor } from "./RegionEditor";
import { CoachingPill, usageLine } from "./ShootStatus";
import { ShootTab } from "./ShootTab";
import { Toasts } from "./Toasts";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

function mockFetch(body: unknown = { ok: true }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify(body), { status: 200 }));
}
const patchBodies = (f: ReturnType<typeof mockFetch>) =>
  f.mock.calls.filter(([, init]) => init?.method === "PATCH").map(([url, init]) => ({ url: String(url), body: JSON.parse(String(init!.body)) }));

const state = (extra: Partial<SessionState> = {}) => sessionState(extra);
const session = (extra: Partial<SessionState["session"]>) => ({ ...sessionState().session, ...extra });

describe("honesty band", () => {
  it("says MOCK PROVIDER for the mock coach and SIMULATED for replays; nothing otherwise", () => {
    const { rerender } = renderWithCtx(<HonestyBand />, makeCtx({ state: state({ session: session({ assess_provider: "mock" }) }) }));
    expect(screen.getByTestId("mock-banner")).toHaveTextContent("MOCK PROVIDER");
    expect(screen.getByTestId("mock-banner")).not.toHaveTextContent("SIMULATED");
    rerender(
      <HonestyBandIn ctx={makeCtx({ state: state({ session: session({ assess_provider: "claude", simulated: true }) }) })} />,
    );
    expect(screen.getByTestId("mock-banner")).toHaveTextContent("SIMULATED");
    rerender(<HonestyBandIn ctx={makeCtx({ state: state() })} />);
    expect(screen.queryByTestId("mock-banner")).toBeNull();
  });
});

function HonestyBandIn({ ctx }: { ctx: AppCtx }) {
  return (
    <AppContext.Provider value={ctx}>
      <HonestyBand />
    </AppContext.Provider>
  );
}

describe("network pill", () => {
  it("combines the live connection with the provider's health", () => {
    expect(netStatus("open", state()).label).toBe("Claude · online");
    expect(netStatus("closed", state())).toMatchObject({ glyph: "✕", label: "Offline" });
    expect(netStatus("reconnecting", state()).label).toBe("Reconnecting…");
    const down = netStatus("open", state({ provider_health: { claude: { ok: false, at: "", error: "timeout" } } }));
    expect(down.label).toBe("Claude · unavailable");
    expect(down.detail).toContain("timeout");
  });
});

describe("toasts", () => {
  it("shows glyph, text and source in a polite live region", () => {
    renderWithCtx(<Toasts />, makeCtx({ toasts: [{ id: 1, glyph: "✓", text: "Region deleted", source: "KEYBOARD", tone: "ok" }] }));
    const region = screen.getByTestId("toasts");
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveTextContent("Region deleted");
    expect(region).toHaveTextContent("KEYBOARD");
  });
});

describe("coaching pill", () => {
  it("shows the call meter and pauses from the popover", async () => {
    const f = mockFetch({ config: { received_cue: "speech" } });
    renderWithCtx(<CoachingPill />, makeCtx({ state: state() }));
    expect(screen.getByTestId("usage")).toHaveTextContent("12 / 40 calls · ≈ $0.34");
    await userEvent.click(screen.getByRole("button", { expanded: false }));
    expect(await screen.findByText(/Spoken: says/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Paused" }));
    expect(patchBodies(f)).toEqual([{ url: "/api/sessions/s1", body: { coaching_paused: true } }]);
    await userEvent.click(screen.getByRole("button", { name: "Raise cap" }));
    expect(patchBodies(f)[1].body).toEqual({ max_model_calls: 50 });
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("formats usage without a cap", () => {
    expect(usageLine(3, null, 0.1)).toBe("3 calls · ≈ $0.10");
  });
});

describe("filmstrip", () => {
  const caps = [
    makeCapture("a", 1, { latest_assessment: assessment({ result: { ...assessment().result!, verdict: "needs_retake" } }) }),
    makeCapture("b", 2, { pairing: { late_raw: true }, raw_name: "P2.ORF" }),
  ];
  it("renders 64×48 thumbs with a glyph + word, marks the selected one, and filters", async () => {
    const onFilter = vi.fn();
    const onSelect = vi.fn();
    renderWithCtx(
      <Filmstrip captures={caps} total={2} filter="all" onFilter={onFilter} selectedId="b" onSelect={onSelect} />,
      makeCtx({ state: state({ captures: caps, pending_files: [{ key: "k1", name: "P3.JPG", status: "stabilizing", note: null }] }) }),
    );
    const one = screen.getByRole("button", { name: /Photo #1.*Needs retake/ });
    expect(one).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: /Photo #2.*late RAW attached/ })).toHaveAttribute("aria-pressed", "true");
    expect(within(screen.getByTestId("film-2")).getByText("+RAW")).toBeInTheDocument();
    // The pending file is "still being written", with no percentage.
    const pending = screen.getByTestId("pending-P3.JPG");
    expect(within(pending).getByRole("img")).toHaveAccessibleName(/P3\.JPG · Still being written$/);
    expect(pending.textContent).not.toMatch(/%/);
    await userEvent.click(one);
    expect(onSelect).toHaveBeenCalledWith("a");
    await userEvent.click(screen.getByRole("button", { name: "Keepers" }));
    expect(onFilter).toHaveBeenCalledWith("keepers");
    expect(screen.getByRole("button", { name: "All 2" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("region editor", () => {
  const regions: Region[] = [
    { id: "r1", label: "Toe", x: 0.1, y: 0.1, w: 0.2, h: 0.2 },
    { id: "r2", label: "Heel", x: 0.5, y: 0.1, w: 0.2, h: 0.2 },
    { id: "r3", label: "Logo", x: 0.1, y: 0.5, w: 0.2, h: 0.2 },
  ];
  const full = { ...shot, sharp_regions: regions };
  const renderEditor = (s = full) => {
    const ctx = makeCtx({ state: state({ shots: [s] }) });
    renderWithCtx(<RegionEditor src="/x.jpg" alt="Photo #1" shot={s} aspect={1.5} />, ctx);
    return ctx;
  };

  it("labels regions 1–3 and refuses a fourth with a toast", () => {
    const ctx = renderEditor();
    expect(screen.getByRole("button", { name: "1 Toe" })).toBeInTheDocument();
    expect(screen.getByText(/3 of 3 regions/)).toBeInTheDocument();
    fireEvent.pointerDown(screen.getByTestId("photo-frame"), { button: 0, clientX: 5, clientY: 5 });
    expect(ctx.toast).toHaveBeenCalledWith(expect.objectContaining({ text: "3 regions max. Delete one first" }));
  });

  it("draws a new region by dragging, saves it on the shot and opens the name field", () => {
    const f = mockFetch({});
    renderEditor({ ...shot, sharp_regions: regions.slice(0, 1) });
    const frame = screen.getByTestId("photo-frame");
    vi.spyOn(frame, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 300, height: 200, right: 300, bottom: 200, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.pointerDown(frame, { button: 0, clientX: 30, clientY: 20 });
    fireEvent.pointerMove(frame, { clientX: 150, clientY: 120 });
    expect(screen.getByText("New region · 40 × 50%")).toBeInTheDocument();
    fireEvent.pointerUp(frame, { clientX: 150, clientY: 120 });
    const saved = patchBodies(f)[0].body.sharp_regions as Region[];
    expect(saved.map((r) => r.id)).toEqual(["r1", "r2"]);
    expect(saved[1]).toMatchObject({ label: "Region 2", x: 0.1, y: 0.1, w: 0.4, h: 0.5 });
    expect(screen.getByRole("textbox", { name: "Name for region 2" })).toHaveValue("Region 2");
  });

  it("shows the count while there is room", () => {
    renderEditor({ ...shot, sharp_regions: regions.slice(0, 1) });
    expect(screen.getByText("Drag to draw · 1 of 3 used · click a label to rename")).toBeInTheDocument();
  });

  it("deletes the selected region with Backspace and saves the shot", async () => {
    const f = mockFetch({});
    renderEditor();
    const rect = screen.getByRole("button", { name: "2 Heel" }).parentElement!;
    fireEvent.pointerDown(rect, { button: 0 });
    expect(await screen.findByRole("button", { name: /Delete/ })).toBeInTheDocument();
    await act(async () => {
      fireEvent.keyDown(window, { key: "Backspace" });
    });
    const saved = patchBodies(f)[0];
    expect(saved.url).toBe(`/api/sessions/s1/shots/${shot.id}`);
    expect(saved.body.sharp_regions.map((r: Region) => r.id)).toEqual(["r1", "r3"]);
    expect(screen.queryByRole("button", { name: "2 Heel" })).toBeNull();
  });

  it("renames by clicking the label, and Backspace while typing edits the name only", async () => {
    const f = mockFetch({});
    renderEditor();
    await userEvent.click(screen.getByRole("button", { name: "1 Toe" }));
    const input = screen.getByRole("textbox", { name: "Name for region 1" });
    await userEvent.clear(input);
    await userEvent.type(input, "Toe box{Backspace}x{Enter}");
    const saved = patchBodies(f);
    expect(saved).toHaveLength(1);
    // "Toe box", Backspace → "Toe bo", then "x" → "Toe box": Backspace edits the text, not the regions.
    expect(saved[0].body.sharp_regions[0]).toMatchObject({ id: "r1", label: "Toe box" });
    expect(saved[0].body.sharp_regions).toHaveLength(3);
  });
});

describe("shoot tab", () => {
  it("shows the waiting state before the first photo", () => {
    mockFetch({});
    renderWithCtx(<ShootTab />, makeCtx({ state: state() }));
    expect(screen.getByTestId("stage-waiting")).toHaveTextContent("Waiting for the first photo…");
    expect(screen.getByTestId("stage-waiting")).toHaveTextContent("The app can’t see the camera itself.");
    expect(screen.getByText("No photos yet. They appear here as files land in the watch folder.")).toBeInTheDocument();
  });

  it("collapses the shot rail with [ but not while typing", () => {
    mockFetch({});
    const { container } = renderWithCtx(<ShootTab />, makeCtx({ state: state() }));
    const root = container.querySelector(".shoot")!;
    fireEvent.keyDown(window, { key: "[" });
    expect(root).toHaveClass("rail-collapsed");
    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "[" });
    expect(root).toHaveClass("rail-collapsed");
    input.remove();
  });

  it("follows the newest photo and steps back with ←", () => {
    mockFetch({});
    const caps = [makeCapture("a", 1), makeCapture("b", 2)];
    renderWithCtx(<ShootTab />, makeCtx({ state: state({ captures: caps }) }));
    expect(screen.getByRole("button", { name: /Photo #2/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(screen.getByRole("button", { name: /Photo #1/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Follow newest/ })).toBeInTheDocument();
  });
});

describe("brightness inspector", () => {
  const stats = (hi: number) => ({
    mean_luminance: 120, p01_luminance: 5, p99_luminance: 250, highlight_clip_fraction: hi, shadow_clip_fraction: 0,
    channel_highlight_clip: {}, channel_shadow_clip: {}, laplacian_var: 900, tenengrad_mean: 1, gradient_p90: 1,
  });
  const cap = makeCapture("a", 1, {
    evidence: {
      available: true, width: 2400, height: 1600, crops: [], has_clip_overlay: true,
      measurements: {
        image: { width: 2400, height: 1600, orientation_tag: null, icc_profile: null, color_assumption: "sRGB" },
        global: { ...stats(0.001), histogram: Array(64).fill(1) },
        regions: { r1: { ...stats(0.031), rect: [0, 0, 1, 1], px_size: [1, 1], histogram: Array(64).fill(1) } },
        notes: {}, caveats: [],
      },
    },
    histogram_insights: {
      summary: "3.1% of the forefoot mesh is pure white",
      regions: [{ scope: "forefoot mesh", region_id: "r1", headline: "3.1% of the forefoot mesh is pure white", shape: "", severity: "problem", zones: {}, highlight_clip: 0.031, shadow_clip: 0,
        findings: [{ scope: "forefoot mesh", severity: "problem", zone: "clip_high", headline: "3.1% of the forefoot mesh is pure white", detail: "Detail is gone there." }] }],
      overall: { scope: "whole frame", headline: "Mostly mid-tones", shape: "Mostly mid-tones", severity: "ok", zones: {}, highlight_clip: 0.001, shadow_clip: 0,
        findings: [{ scope: "whole frame", severity: "ok", zone: "midtones", headline: "No lost detail in the frame", detail: "Nothing is pure white or pure black." }] },
      how_to_read: ["Left to right is dark to bright."],
      caveat: "Measured on the processed JPEG, not the RAW file.",
    },
  });

  it("lists marked regions first, leads with the worst one, and explains itself", async () => {
    mockFetch({});
    renderWithCtx(<ShootTab />, makeCtx({ state: state({ captures: [cap] }) }));
    const insp = screen.getByRole("region", { name: "Brightness" });
    expect(within(insp).getByRole("button", { name: /1 forefoot mesh/ })).toHaveAttribute("aria-pressed", "true");
    expect(insp).toHaveTextContent("Marked regions first");
    expect(insp).toHaveTextContent("1 forefoot mesh · Detail lost: 3.1% of the forefoot mesh is pure white");
    expect(insp).toHaveTextContent("Detail is gone there.");
    expect(insp).toHaveTextContent("From JPEG, not RAW");
    await userEvent.click(within(insp).getByRole("button", { name: /Whole frame/ }));
    expect(insp).toHaveTextContent("Whole frame · OK: Mostly mid-tones");
    await userEvent.click(within(insp).getByRole("button", { name: /How to read this/ }));
    expect(within(insp).getByRole("dialog")).toHaveTextContent("Left to right is dark to bright.");
  });

  it("pins a zone and captions it on the photo; H toggles the lost-detail overlay", async () => {
    mockFetch({});
    renderWithCtx(<ShootTab />, makeCtx({ state: state({ captures: [cap] }) }));
    await userEvent.click(screen.getByRole("button", { name: "pure white" }));
    expect(screen.getByText("Solid red = pure white, no detail")).toBeInTheDocument();
    const lost = screen.getByRole("button", { name: /Lost detail/ });
    expect(lost).toHaveAttribute("aria-pressed", "false");
    fireEvent.keyDown(window, { key: "h" });
    expect(lost).toHaveAttribute("aria-pressed", "true");
  });
});
