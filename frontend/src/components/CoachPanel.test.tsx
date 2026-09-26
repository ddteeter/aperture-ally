import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { AppContext, type AppCtx } from "../AppContext";
import { CoachPanel } from "./CoachPanel";
import { assessment, baselineCapture, experiment, followUpCapture, shot } from "../test/fixtures";

function ctx(over: Partial<AppCtx> = {}): AppCtx {
  return {
    sid: "s1",
    state: null,
    refresh: vi.fn(async () => {}),
    refreshSessions: vi.fn(async () => {}),
    run: async (_label, fn) => fn(),
    subscribe: () => () => {},
    received: null,
    pendingNote: null,
    setPendingNote: () => {},
    ...over,
  };
}

function wrap(children: ReactNode, c: AppCtx = ctx()) {
  return render(<AppContext.Provider value={c}>{children}</AppContext.Provider>);
}

afterEach(() => vi.restoreAllMocks());

describe("CoachPanel", () => {
  it("renders a completed comparison assessment with criteria, exposure note, meta and experiment", () => {
    const cap = followUpCapture(assessment());
    wrap(
      <CoachPanel
        capture={cap}
        shot={shot}
        captures={[baselineCapture, cap]}
        experiments={[experiment]}
        keeper={null}
      />,
    );
    const live = screen.getByTestId("coach-spoken");
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toHaveTextContent("Mock coach: Better. The glare is gone.");

    expect(screen.getByText(/AI verdict/).closest(".chip")).toHaveTextContent("AI verdict: usable candidate");
    const cmp = screen.getByTestId("comparison");
    expect(cmp).toHaveTextContent("Comparison vs #1");
    expect(cmp).toHaveTextContent("improved");
    expect(cmp).toHaveTextContent("glare metric 0.552 → 0");

    expect(screen.getByText("Keep this setup and take a safety frame.").tagName).toBe("STRONG");

    // criterion text is looked up from the shot
    const table = screen.getByRole("table", { name: "Criteria" });
    expect(within(table).getByText("c1: Mesh weave is sharp")).toBeInTheDocument();
    expect(within(table).getByText("pass")).toBeInTheDocument();
    expect(within(table).getByText("uncertain")).toBeInTheDocument();

    expect(screen.getByText("Exposure equivalence not applied:")).toBeInTheDocument();
    expect(screen.getByText("light is flash: equivalence does not hold")).toBeInTheDocument();
    expect(screen.getByText(/What made this frame work/)).toBeInTheDocument();

    const meta = screen.getByTestId("coach-meta");
    expect(meta).toHaveTextContent("mock-heuristic-v1");
    expect(meta).toHaveTextContent("coach-2026-09-26.1");
    expect(meta).toHaveTextContent("156 ms");
    expect(meta).toHaveTextContent("cost n/a");
    expect(meta).toHaveTextContent("speech spoken");

    expect(screen.getByText(/Experiment: #1 → #2/)).toBeInTheDocument();
    expect(screen.getByText("Move the light about a hand-width camera-left.")).toBeInTheDocument();

    // No Retry for a successful assessment; keeper is never auto-accepted
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(screen.getByText(/No keeper yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept photo #2 as keeper for Upper texture (mesh close-up)" })).toBeInTheDocument();
  });

  it("requires an explicit confirm step before accepting a keeper", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ id: "k1" }), { status: 201 }));
    const cap = followUpCapture(assessment());
    const c = ctx();
    wrap(<CoachPanel capture={cap} shot={shot} captures={[baselineCapture, cap]} experiments={[]} keeper={null} />, c);
    await userEvent.click(screen.getByRole("button", { name: /Accept photo #2 as keeper/ }));
    expect(fetchMock).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Yes, accept photo #2" }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/shots/shot-1/keeper");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toMatchObject({ capture_id: "cap-2" });
    expect(c.refresh).toHaveBeenCalled();
  });

  it("shows the error and a Retry button for a failed assessment (AI unavailable)", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ queued: true }), { status: 202 }));
    const failed = assessment({ status: "failed", result: null, error: "AI unavailable: mock provider unavailable", speech_status: "not_applicable" });
    const cap = followUpCapture(failed, { processing_state: "failed", error: failed.error });
    wrap(<CoachPanel capture={cap} shot={shot} captures={[baselineCapture, cap]} experiments={[]} keeper={null} />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Analysis failed: AI unavailable: mock provider unavailable");
    expect(alert).toHaveTextContent(/Local features .* still work/);
    expect(screen.queryByTestId("comparison")).not.toBeInTheDocument();

    await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/captures/cap-2/assess", expect.objectContaining({ method: "POST" }));
  });

  it("shows Analysing… while an assessment is running", () => {
    const running = assessment({ status: "running", result: null });
    const cap = followUpCapture(running, { processing_state: "analyzing" });
    wrap(<CoachPanel capture={cap} shot={shot} captures={[cap]} experiments={[]} keeper={null} />);
    expect(screen.getByTestId("coach-spoken")).toHaveTextContent("Analysing…");
    expect(screen.getByRole("button", { name: "Review again" })).toBeDisabled();
  });
});
