import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { makeCtx, renderWithCtx } from "../test/ctx";
import { assessment, followUpCapture, sessionState, shot } from "../test/fixtures";
import { CoachPanel } from "./CoachPanel";
import { RegionEditor } from "./RegionEditor";
import { CoachingPill } from "./ShootStatus";

afterEach(() => vi.restoreAllMocks());

// Known risk from the redesign: the analysis view binds Esc → cancel on window before a popover
// opens, so the popover's own Esc listener ran second and the analysis was cancelled too.
it("Esc with a popover open during analysis closes the popover and does not cancel the analysis", async () => {
  const f = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({ config: {} })));
  const running = assessment({ status: "running", result: null, created_at: new Date().toISOString() });
  const cap = followUpCapture(running, { processing_state: "analyzing" });
  renderWithCtx(
    <>
      <CoachPanel capture={cap} shot={shot} captures={[cap]} experiments={[]} keeper={null} />
      <CoachingPill />
    </>,
    makeCtx({ state: sessionState() }),
  );
  await userEvent.click(screen.getByRole("button", { expanded: false }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  await new Promise((r) => setTimeout(r, 20));
  expect(f.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/cancel"))).toEqual([]);
  // With the popover gone, Esc cancels the analysis as before.
  fireEvent.keyDown(window, { key: "Escape" });
  await vi.waitFor(() => expect(f.mock.calls.some(([u]) => String(u).includes("/cancel"))).toBe(true));
});

it("Esc with a region selected during analysis deselects it and does not cancel the analysis", async () => {
  const f = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("{}"));
  const running = assessment({ status: "running", result: null, created_at: new Date().toISOString() });
  const cap = followUpCapture(running, { processing_state: "analyzing" });
  const s = { ...shot, sharp_regions: [{ id: "r1", label: "Toe", x: 0.1, y: 0.1, w: 0.2, h: 0.2 }] };
  renderWithCtx(
    <>
      <CoachPanel capture={cap} shot={s} captures={[cap]} experiments={[]} keeper={null} />
      <RegionEditor src="/x.jpg" alt="Photo #2" shot={s} aspect={1.5} />
    </>,
    makeCtx({ state: sessionState({ shots: [s] }) }),
  );
  fireEvent.pointerDown(screen.getByRole("button", { name: "1 Toe" }).parentElement!, { button: 0 });
  expect(await screen.findByRole("button", { name: /Delete/ })).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "Escape" });
  await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Delete/ })).toBeNull());
  await new Promise((r) => setTimeout(r, 20));
  expect(f.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/cancel"))).toEqual([]);
});
