import { act, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ComparisonMetrics, SessionState } from "../api/types";
import { makeCtx, renderWithCtx } from "../test/ctx";
import { assessment, baselineCapture, experiment, followUpCapture, makeCapture, sessionState, shot } from "../test/fixtures";
import { CoachPanel, coachMode } from "./CoachPanel";

afterEach(() => vi.restoreAllMocks());

function mockFetch(body: unknown = { ok: true }, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify(body), { status }));
}
const call = (f: ReturnType<typeof mockFetch>, i = 0) => {
  const [url, init] = f.mock.calls[i];
  return { url, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined };
};
function ctxWith(extra: Partial<SessionState> = {}) {
  return makeCtx({ state: sessionState(extra) });
}

const retakeAssessment = () =>
  assessment({
    kind: "assess",
    baseline_capture_id: null,
    provider: "claude",
    model_requested: "claude-sonnet",
    model_resolved: "claude-sonnet-4.5",
    usage: { input_tokens: 1800, output_tokens: 300 },
    cost_estimate_usd: 0.028,
    timings: { total_ms: 4200 },
    warnings: ["Image stabilisation is on, but Setup says tripod."],
    result: {
      verdict: "needs_retake",
      criterion_results: [
        { criterion_id: "c1", result: "pass", evidence: "" },
        { criterion_id: "c2", result: "fail", evidence: "3.1% pure white" },
      ],
      observations: [{ region_id: "r1", observation: "3.1% of the mesh is clipped to pure white.", evidence_source: "measurement", severity: "major" }],
      primary_action: {
        instruction: "Move the light a hand-width camera-left.",
        explanation: "The mesh is glaring.",
        expected_effect: "Mesh detail comes back.",
        tradeoff: "The right edge falls darker.",
        prerequisites: [],
        hold_constant: null,
        exposure_target: null,
      },
      alternative_causes: ["The shoe is angled toward the light.", "Exposure is a little high."],
      comparison: null,
      question_for_user: "Should the mesh show texture or glow?",
      teaching_prompt: "Look at the reflection from behind the camera.",
      spoken_text: "Needs retake. Move the light left.",
    },
  });

describe("coachMode", () => {
  it("maps captures to panel states", () => {
    expect(coachMode(null)).toBe("brief");
    expect(coachMode(followUpCapture(assessment({ status: "running", result: null }), { processing_state: "analyzing" }))).toBe("analysing");
    expect(coachMode(followUpCapture(assessment()))).toBe("comparison");
    expect(coachMode(followUpCapture(retakeAssessment()))).toBe("verdict");
    expect(coachMode(followUpCapture(assessment({ status: "failed", result: null })))).toBe("failure");
    expect(coachMode(followUpCapture(null, { processing_state: "failed" }))).toBe("bad_file");
    expect(coachMode(followUpCapture(null, { processing_state: "ready" }))).toBe("no_verdict");
  });
});

describe("CoachPanel", () => {
  it("shows the active shot's brief when there is no photo yet", () => {
    renderWithCtx(<CoachPanel capture={null} shot={null} captures={[]} experiments={[]} keeper={null} />, ctxWith());
    expect(screen.getByText("Shot 1 · brief")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: shot.title })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Must show" })).getByText("mesh")).toBeInTheDocument();
    expect(screen.getByText("Mesh weave is sharp")).toBeInTheDocument();
    expect(screen.getByText("Coaching tips appear once the first photo has been assessed.")).toBeInTheDocument();
    expect(screen.queryByTestId("keeper")).not.toBeInTheDocument();
  });

  it("explains a later bracket frame (not auto-coached) and still offers a review", async () => {
    const f = mockFetch({ queued: true });
    const cap = followUpCapture(null, { processing_state: "ready", exif: { bracket: { kind: "AE", shot: 3 } } });
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[cap]} experiments={[]} keeper={null} />, ctxWith());
    expect(screen.getByText("Bracket frame 3")).toBeInTheDocument();
    expect(screen.getByText(/The coach reviews the base frame \(shot 1\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Review #2 anyway" }));
    expect(call(f)).toMatchObject({ url: "/api/captures/cap-2/assess", method: "POST" });
  });

  it("shows analysis steps and cancels with the button or Esc", async () => {
    const f = mockFetch({ cancelled: true });
    const running = assessment({ status: "running", result: null, provider: "claude", created_at: new Date().toISOString() });
    const cap = followUpCapture(running, { processing_state: "analyzing" });
    const c = ctxWith();
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[cap]} experiments={[]} keeper={null} />, c);
    expect(screen.getByTestId("coach-spoken")).toHaveTextContent("Analysing photo #2");
    expect(screen.getByText("Analysing #2")).toBeInTheDocument();
    expect(screen.getByText(/Claude reviewing against 2 criteria/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Cancel analysis/ }));
    expect(call(f)).toMatchObject({ url: "/api/captures/cap-2/cancel", method: "POST" });
    expect(c.toast).toHaveBeenCalledWith(expect.objectContaining({ text: "Analysis of #2 cancelled" }));
    fireEvent.keyDown(window, { key: "Escape" });
    await vi.waitFor(() => expect(f).toHaveBeenCalledTimes(2));
  });

  it("renders a retake verdict: do this, why, coach asks, criteria, causes, model line", async () => {
    const f = mockFetch({ intent: "answer", answer: "ok", voice_turn_id: "v1" });
    const cap = followUpCapture(retakeAssessment(), { baseline_capture_id: null });
    const c = ctxWith();
    const shown = vi.fn();
    window.addEventListener("aa:show-zone", shown);
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[cap]} experiments={[]} keeper={null} />, c);

    expect(screen.getByRole("heading", { name: "Needs retake" })).toBeInTheDocument();
    expect(screen.getByText("Photo #2 · verdict in 4.2 s · spoken")).toBeInTheDocument();
    expect(screen.getByText("Move the light a hand-width camera-left.")).toBeInTheDocument();
    expect(screen.getByText("Starting point not calculated: light is flash: equivalence does not hold")).toBeInTheDocument();
    expect(screen.getByText("The right edge falls darker.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show me on the photo ↙" }));
    expect(shown).toHaveBeenCalledTimes(1);
    expect((shown.mock.calls[0][0] as CustomEvent).detail).toEqual({ regionId: "r1", zone: "clip_high" });
    window.removeEventListener("aa:show-zone", shown);

    // coach question: typed answer goes through the voice pipeline
    expect(screen.getByText("Should the mesh show texture or glow?")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Answer by voice (hold the remote) or type"), "Texture{Enter}");
    expect(call(f)).toMatchObject({ url: "/api/voice/text", body: { text: "Texture", session_id: "s1", capture_id: "cap-2" } });

    const crit = screen.getByRole("list", { name: "Criteria" });
    expect(within(crit).getByText("Pass")).toBeInTheDocument();
    expect(within(crit).getByText("Fail")).toBeInTheDocument();
    expect(screen.getByText("1 pass · 1 fail")).toBeInTheDocument();
    expect(screen.getByText("Look at the reflection from behind the camera.")).toBeInTheDocument();
    expect(screen.getByText("Image stabilisation is on, but Setup says tripod.")).toBeInTheDocument();

    const causes = screen.getByRole("button", { name: /Other possible causes \(2\)/ });
    expect(screen.queryByText("Exposure is a little high.")).not.toBeInTheDocument();
    await userEvent.click(causes);
    expect(screen.getByText("Exposure is a little high.")).toBeInTheDocument();

    expect(screen.getByTestId("coach-meta")).toHaveTextContent("Claude · claude-sonnet-4.5 · 2.1k tokens · $0.028");
    // a retake is not offered as a primary keeper, only "anyway"
    expect(screen.getByRole("button", { name: "Accept #2 as keeper anyway…" })).toBeInTheDocument();
  });

  it("renders an improved comparison from measured metrics and rates the advice", async () => {
    const f = mockFetch({ ...experiment, user_rating: "helpful" });
    const metrics: ComparisonMetrics = {
      baseline_capture_id: "cap-1",
      baseline_seq: 1,
      framing: { score: 0.94, comparable: true },
      ev_delta: -0.4,
      ev_note: "Exposure was manual, so this change came from the settings",
      regions: [
        {
          scope: "r1",
          label: "forefoot mesh",
          sharpness_change_pct: 36,
          mean_before: 120,
          mean_after: 121,
          highlight_clip_before: 0.031,
          highlight_clip_after: 0.004,
          shadow_clip_before: 0,
          shadow_clip_after: 0,
          histogram_before: Array(64).fill(1),
          histogram_after: Array(64).fill(2),
        },
      ],
      global: {
        scope: "global",
        label: "Whole frame",
        sharpness_change_pct: null,
        mean_before: 124,
        mean_after: 118,
        highlight_clip_before: 0.01,
        highlight_clip_after: 0.002,
        shadow_clip_before: 0,
        shadow_clip_after: 0,
        histogram_before: null,
        histogram_after: null,
      },
    };
    const base = makeCapture("cap-1", 1, { latest_assessment: retakeAssessment() });
    const cap = followUpCapture(assessment(), { comparison_metrics: metrics, user_reported_change: "Moved the light left." });
    const c = ctxWith();
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[base, cap]} experiments={[experiment]} keeper={null} />, c);

    expect(screen.getByRole("heading", { name: "Improved" })).toBeInTheDocument();
    expect(screen.getByText("#2 compared with #1 · usable candidate")).toBeInTheDocument();
    expect(screen.getByTestId("comparison")).toHaveTextContent("Comparison vs #1: Improved");
    expect(screen.getByText("Framing match 94%")).toBeInTheDocument();
    expect(screen.getByText("glare metric 0.552 → 0")).toBeInTheDocument();
    expect(screen.getByText("Pure white on the forefoot mesh")).toBeInTheDocument();
    expect(screen.getByText("+36% sharper")).toBeInTheDocument();
    expect(screen.getByText("Overall darker")).toBeInTheDocument();
    expect(screen.getByText("mean 124 → 118 of 255")).toBeInTheDocument();
    expect(screen.getByText("≈ −0.4 EV")).toBeInTheDocument();
    expect(screen.getByAltText("forefoot mesh in #1 (before)")).toHaveAttribute("src", "/api/captures/cap-1/image/crop_r1");
    expect(screen.getByAltText("forefoot mesh in #2 (after)")).toHaveAttribute("src", "/api/captures/cap-2/image/crop_r1");
    expect(screen.getByText("Criteria #1 → #2")).toBeInTheDocument();
    const delta = screen.getByRole("list", { name: "Criteria before and after" });
    expect(within(delta).getAllByRole("listitem")[1]).toHaveTextContent("✕#1 Fail→?#2 UnsureNo blown highlights on the mesh");
    expect(screen.getByText("“Moved the light left.”")).toBeInTheDocument();
    // improved: no NEXT block
    expect(screen.queryByText("Next")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Helpful/ }));
    expect(call(f)).toMatchObject({ url: "/api/experiments/exp-1", method: "PATCH", body: { user_rating: "helpful" } });
    expect(c.toast).toHaveBeenCalledWith(expect.objectContaining({ text: "Marked helpful" }));
    expect(screen.getByRole("button", { name: /Helpful/ })).toHaveAttribute("aria-pressed", "true");

    await userEvent.type(screen.getByLabelText("Lesson, in your words"), "Side-light shows the weave.");
    await userEvent.click(screen.getByRole("button", { name: "Save lesson" }));
    expect(call(f, 1)).toMatchObject({ url: "/api/experiments/exp-1", body: { lesson: "Side-light shows the weave." } });
    expect(c.toast).toHaveBeenCalledWith(expect.objectContaining({ text: "Lesson saved" }));
  });

  it("degrades to histogram sentences without metrics, and shows NEXT for a worse retake", () => {
    const worse = assessment({
      result: {
        ...assessment().result!,
        verdict: "needs_retake",
        comparison: { baseline_capture_id: "cap-1", outcome: "worse", evidence: "The light went frontal." },
        primary_action: { ...assessment().result!.primary_action!, instruction: "Put the light back, then slide it left." },
      },
    });
    const cap = followUpCapture(worse, { histogram_changes: { baseline_seq: 1, changes: ["Highlights grew on the mesh."] } });
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[baselineCapture, cap]} experiments={[]} keeper={null} />, ctxWith());
    expect(screen.getByRole("heading", { name: "Worse" })).toBeInTheDocument();
    expect(screen.getByText("Highlights grew on the mesh.")).toBeInTheDocument();
    expect(screen.queryByText(/Framing match/)).not.toBeInTheDocument();
    expect(screen.getByText("Put the light back, then slide it left.")).toBeInTheDocument();
    expect(screen.getByText(/Starting point not calculated/)).toBeInTheDocument();
  });

  it("opens the Compare with… picker for an uncertain comparison and re-compares", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (String(url).endsWith("/baseline-candidates"))
        return new Response(
          JSON.stringify([
            { capture_id: "cap-1", seq: 1, verdict: "needs_retake", framing: { score: 0.64, comparable: false }, is_current_baseline: true },
            { capture_id: "cap-0", seq: 0, verdict: "needs_retake", framing: { score: 0.86, comparable: true }, is_current_baseline: false },
          ]),
        );
      return new Response(JSON.stringify({ queued: true }));
    });
    const unc = assessment({
      result: { ...assessment().result!, verdict: "uncertain", comparison: { baseline_capture_id: "cap-1", outcome: "uncertain", evidence: "Framing moved." } },
    });
    const cap = followUpCapture(unc, {
      comparison_metrics: { baseline_capture_id: "cap-1", baseline_seq: 1, framing: { score: 0.64, comparable: false }, ev_delta: null, ev_note: null, regions: [], global: null },
    });
    const c = ctxWith();
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[baselineCapture, cap]} experiments={[]} keeper={null} />, c);
    expect(screen.getByRole("heading", { name: "Can’t compare" })).toBeInTheDocument();
    expect(screen.getByText("Framing match 64% · too low")).toBeInTheDocument();
    expect(screen.getByText("Criteria · #2 on its own")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Compare with/ })).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(await screen.findByRole("button", { name: /#0 · Needs retake/ }));
    expect(f.mock.calls.map(([u, i]) => `${i?.method ?? "GET"} ${u}`)).toEqual([
      "GET /api/captures/cap-2/baseline-candidates",
      "PATCH /api/captures/cap-2",
      "POST /api/captures/cap-2/compare",
    ]);
    expect(c.toast).toHaveBeenCalledWith(expect.objectContaining({ text: "Comparing #2 with #0" }));
  });

  it("closes the Compare with… picker on Esc (without cancelling voice) and on a click outside", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("[]"));
    const unc = assessment({
      result: { ...assessment().result!, verdict: "uncertain", comparison: { baseline_capture_id: "cap-1", outcome: "uncertain", evidence: "Framing moved." } },
    });
    const cap = followUpCapture(unc, {
      comparison_metrics: { baseline_capture_id: "cap-1", baseline_seq: 1, framing: { score: 0.64, comparable: false }, ev_delta: null, ev_note: null, regions: [], global: null },
    });
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[baselineCapture, cap]} experiments={[]} keeper={null} />, ctxWith());
    const btn = screen.getByRole("button", { name: /Compare with/ });
    expect(btn).toHaveAttribute("aria-expanded", "true");
    const esc = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    const later = vi.fn();
    window.addEventListener("keydown", later);
    act(() => void document.body.dispatchEvent(esc));
    window.removeEventListener("keydown", later);
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(later).not.toHaveBeenCalled(); // Esc belonged to the picker, not the voice bar underneath
    await userEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
    fireEvent.mouseDown(document.body);
    expect(btn).toHaveAttribute("aria-expanded", "false");
    f.mockRestore();
  });

  it("requires the confirm dialog before accepting a keeper, then shows Undo", async () => {
    const f = mockFetch({ id: "k1" }, 201);
    const cap = followUpCapture(assessment());
    const c = ctxWith();
    const { rerender } = renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[baselineCapture, cap]} experiments={[]} keeper={null} />, c);
    await userEvent.click(screen.getByRole("button", { name: /Accept #2 as keeper…/ }));
    const dialog = screen.getByRole("dialog", { name: `Accept #2 as the keeper for ${shot.title}?` });
    expect(f).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: /Not yet/ }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    // ⌘↵ opens it too; Accept posts
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /Accept keeper/ }));
    expect(call(f)).toMatchObject({ url: "/api/shots/shot-1/keeper", method: "POST", body: { capture_id: "cap-2" } });
    expect(c.toast).toHaveBeenCalledWith(expect.objectContaining({ glyph: "★", text: "Keeper accepted · #2" }));
    expect(c.refresh).toHaveBeenCalled();

    const keeper = { id: "k1", session_id: "s1", shot_id: shot.id, capture_id: "cap-2", stored_path: null, sha256: null, notes: null, criterion_notes: {}, source: "ui", accepted_at: "", revoked_at: null };
    const { AppContext } = await import("../AppContext");
    rerender(
      <AppContext.Provider value={c}>
        <CoachPanel capture={cap} shot={shot} captures={[baselineCapture, cap]} experiments={[]} keeper={keeper} />
      </AppContext.Provider>,
    );
    expect(screen.getByTestId("keeper")).toHaveTextContent("Keeper accepted · #2");
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(call(f, 1)).toMatchObject({ url: "/api/shots/shot-1/keeper", method: "DELETE" });
  });

  it("offers Retry now / Retry when online when the coach is unavailable", async () => {
    const f = mockFetch({ queued: true });
    const failed = assessment({ status: "failed", result: null, error: "AI unavailable: no network", provider: "claude" });
    const cap = followUpCapture(failed, { processing_state: "failed", error: failed.error });
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[baselineCapture, cap]} experiments={[]} keeper={null} />, ctxWith());
    expect(screen.getByRole("heading", { name: "Coach unavailable" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("AI unavailable: no network");
    expect(screen.getByText("Your photos are safe. Only the coach is unavailable.")).toBeInTheDocument();
    expect(screen.queryByTestId("comparison")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Retry now/ }));
    expect(call(f)).toMatchObject({ url: "/api/captures/cap-2/retry", body: { when: "now" } });
    await userEvent.click(screen.getByRole("button", { name: "Retry when online" }));
    expect(call(f, 1)).toMatchObject({ body: { when: "online" } });
  });

  it("shows the armed retry state", () => {
    const failed = assessment({ status: "failed", result: null, error: "AI unavailable: no network" });
    const cap = followUpCapture(failed, { processing_state: "failed", retry_when_online: true });
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[cap]} experiments={[]} keeper={null} />, ctxWith());
    expect(screen.getByRole("button", { name: "✓ Will retry when online" })).toBeDisabled();
  });

  it("offers Read again for a bad file", async () => {
    const f = mockFetch();
    const cap = followUpCapture(null, { processing_state: "failed", error: "The file ended early (truncated JPEG)." });
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[cap]} experiments={[]} keeper={null} />, ctxWith());
    expect(screen.getByRole("heading", { name: "#2 couldn’t be read" })).toBeInTheDocument();
    expect(screen.getByText("The file ended early (truncated JPEG).")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Read again" }));
    expect(call(f)).toMatchObject({ url: "/api/captures/cap-2/reread", method: "POST" });
  });

  it("shows paused coaching with Resume (P) and Raise cap, and 'No verdict (paused)'", async () => {
    const f = mockFetch({});
    const st = sessionState();
    const c = makeCtx({
      state: { ...st, session: { ...st.session, coaching_paused: true, paused_reason: "Call cap reached" }, usage: { ...st.usage!, exceeded: true, capped_calls: 40 } },
    });
    const cap = followUpCapture(null, { processing_state: "ready" });
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[cap]} experiments={[]} keeper={null} />, c);
    expect(screen.getByRole("heading", { name: "Coaching paused" })).toBeInTheDocument();
    expect(screen.getByText("Call cap reached · 40 paid calls · ≈ $0.34")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No verdict (paused)" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Raise cap to 60" }));
    expect(call(f)).toMatchObject({ url: "/api/sessions/s1", method: "PATCH", body: { max_model_calls: 60 } });
    fireEvent.keyDown(window, { key: "p" });
    await vi.waitFor(() => expect(call(f, 1)).toMatchObject({ body: { coaching_paused: false } }));
  });

  it("offers to move a photo that might belong to another shot", async () => {
    const f = mockFetch({});
    const cap = followUpCapture(assessment(), {
      attribution_ambiguous: true,
      attribution_hint: { shot_id: "shot-0", shot_title: "Hero", matched_capture_seq: 1, framing_score: 0.92, seconds_after_switch: 8 },
    });
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[cap]} experiments={[]} keeper={null} />, ctxWith());
    expect(screen.getByText("#2 might belong to Hero")).toBeInTheDocument();
    expect(screen.getByText("It was taken 8 s after you switched shots and its framing matches #1 (92%).")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Move to Hero" }));
    expect(call(f)).toMatchObject({ url: "/api/captures/cap-2", method: "PATCH", body: { shot_id: "shot-0" } });
  });

  it("lists pending-file problems with Read again / Skip", async () => {
    const f = mockFetch({ ok: true });
    const c = ctxWith({
      pending_files: [
        { key: "k-15", name: "P15.JPG", status: "failed", note: "Truncated JPEG." },
        { key: "k-17", name: "P17.JPG", status: "stabilizing", note: null },
      ],
    });
    renderWithCtx(<CoachPanel capture={null} shot={null} captures={[]} experiments={[]} keeper={null} />, c);
    expect(screen.getByText("P15.JPG couldn’t be read")).toBeInTheDocument();
    expect(screen.getByText("P17.JPG is still being written")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Skip file" }));
    expect(call(f)).toMatchObject({ url: "/api/sessions/s1/pending-files/k-15/skip", method: "POST" });
  });

  it("footer: EXIF grid with missing values and the change note on Enter", async () => {
    const f = mockFetch({ pending_change: "moved the light left" });
    const cap = followUpCapture(retakeAssessment(), { exif: { exposure_time_s: 1 / 125, f_number: 5.6, iso: 200 } });
    const c = ctxWith();
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[cap]} experiments={[]} keeper={null} />, c);
    expect(screen.getByText("1/125 s")).toBeInTheDocument();
    expect(screen.getByText("not in EXIF")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("What I changed"), "moved the light left{Enter}");
    expect(call(f)).toMatchObject({ url: "/api/sessions/s1/change-note", body: { text: "moved the light left" } });
    expect(c.toast).toHaveBeenCalledWith(expect.objectContaining({ text: "Change noted: moved the light left" }));
  });

  it("does not fire shortcuts while typing", () => {
    const f = mockFetch({});
    const running = assessment({ status: "running", result: null });
    const cap = followUpCapture(running, { processing_state: "analyzing" });
    renderWithCtx(<CoachPanel capture={cap} shot={shot} captures={[cap]} experiments={[]} keeper={null} />, ctxWith());
    fireEvent.keyDown(screen.getByLabelText("What I changed"), { key: "Escape" });
    expect(f).not.toHaveBeenCalled();
  });
});
