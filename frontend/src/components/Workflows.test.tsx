import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type { Session, SetupRevisionSummary } from "../api/types";
import { makeCtx, renderWithCtx } from "../test/ctx";
import { CoverageTab } from "./CoverageTab";
import { DiagnosticsTab } from "./DiagnosticsTab";
import { SessionsTab } from "./SessionsTab";
import { SetupTab } from "./SetupTab";
import { ShotListTab } from "./ShotListTab";
import { covShot, makeCoverage, makeDiag, makeSession, makeState, setupRev } from "./workflows.testutil";

afterEach(() => {
  vi.restoreAllMocks();
  window.location.hash = "";
});

describe("CoverageTab", () => {
  const state = () =>
    makeState({
      coverage: makeCoverage([
        covShot("shot-1", "Hero", "accepted", {
          resolved: true,
          keeper: { capture_id: "cap-1", capture_seq: 7, shot_id: "shot-1" } as never,
          keeper_problem: "Keeper file is missing on disk",
        }),
        covShot("shot-2", "Outsole", "missing"),
        covShot("shot-3", "Heel", "needs_retake"),
      ]),
    });

  it("shows the headline, counts, status words and keeper warnings", () => {
    renderWithCtx(<CoverageTab />, makeCtx({ state: state() }));
    expect(screen.getByRole("heading", { name: "Not yet — 2 shots still missing" })).toBeInTheDocument();
    expect(screen.getByText("1 of 3 shots have a keeper", { exact: false })).toBeInTheDocument();
    const hero = screen.getByTestId("coverage-row-Hero");
    expect(hero).toHaveTextContent("Keeper");
    expect(hero).toHaveTextContent("#7");
    expect(hero).toHaveTextContent("Keeper file is missing on disk");
    expect(within(hero).getByRole("img")).toHaveAttribute("src", "/api/captures/cap-1/image/thumb");
    expect(screen.getByTestId("coverage-row-Outsole")).toHaveTextContent("Missing");
    expect(screen.getByTestId("coverage-row-Heel")).toHaveTextContent("Retake →");
    expect(screen.getByText("2 shots have no keeper. They'll be listed as missing in the export.", { exact: false })).toBeInTheDocument();
  });

  it("revokes a keeper only after the inline confirm", async () => {
    const revoke = vi.spyOn(api, "revokeKeeper").mockResolvedValue({ revoked: null });
    const ctx = makeCtx({ state: state() });
    renderWithCtx(<CoverageTab />, ctx);
    await userEvent.click(screen.getByRole("button", { name: "Revoke keeper" }));
    expect(screen.getByText("Revoke #7 as keeper? The shot goes back to candidate. The photo stays.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(revoke).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Revoke keeper" }));
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    expect(revoke).toHaveBeenCalledWith("shot-1");
    await waitFor(() => expect(ctx.refresh).toHaveBeenCalled());
  });

  it("CTA makes the shot active and switches to Shoot", async () => {
    const setActive = vi.spyOn(api, "setActiveShot").mockResolvedValue(makeSession());
    renderWithCtx(<CoverageTab />, makeCtx({ state: state() }));
    await userEvent.click(screen.getByRole("link", { name: "Shoot this: Outsole" }));
    expect(setActive).toHaveBeenCalledWith("s1", "shot-2");
    await waitFor(() => expect(window.location.hash).toBe("#shoot"));
  });

  it("lists the files the export wrote", async () => {
    vi.spyOn(api, "exports").mockResolvedValue({ json: "/o/exports/coverage.json", contact_sheet: "/o/exports/contact_sheet.jpg" });
    renderWithCtx(<CoverageTab />, makeCtx({ state: state() }));
    await userEvent.click(screen.getByRole("button", { name: "Export files" }));
    const st = await screen.findByRole("status");
    expect(st).toHaveTextContent("JSON");
    expect(st).toHaveTextContent("coverage.json");
    expect(st).toHaveTextContent("Contact sheet");
    expect(st).toHaveTextContent("contact_sheet.jpg");
  });
});

describe("SessionsTab", () => {
  it("lists sessions with provider / SIMULATED tags and opens one", async () => {
    const onOpen = vi.fn();
    const sessions: Session[] = [
      makeSession({ id: "s0", name: "Old", assess_provider: "claude", status: "paused" }),
      makeSession({ id: "s1", name: "Current", simulated: true }),
    ];
    renderWithCtx(<SessionsTab sessions={sessions} onOpen={onOpen} />, makeCtx({ state: makeState() }));
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Current");
    expect(rows[1]).toHaveTextContent("MOCK PROVIDER");
    expect(rows[1]).toHaveTextContent("SIMULATED");
    expect(rows[1]).toHaveTextContent("0 / 3");
    expect(rows[2]).toHaveTextContent("Claude");
    expect(rows[2]).toHaveTextContent("Paused");
    await userEvent.click(within(rows[2]).getByRole("button", { name: /^Old/ }));
    expect(onOpen).toHaveBeenCalledWith("s0");
  });

  it("creates a session from a project's template, with day notes, provider, teaching and outdoor theme", async () => {
    const create = vi.spyOn(api, "createSession").mockResolvedValue(makeSession({ id: "new" }));
    const tpl = (id: string, name: string, n: number, source: string | null, preferences = "") => ({
      id, project_id: "p1", name, preferences, version: 1, source, archived: false, created_at: "", updated_at: "",
      shot_count: n, shot_titles: [],
    });
    vi.spyOn(api, "projects").mockResolvedValue([
      { id: "p1", name: "Running blog", preferences: "Soft backgrounds.", archived: false, created_at: "", updated_at: "",
        templates: [tpl("t-shoe", "Shoe review", 6, "running_shoe", "Laces tidy."), tpl("t-app", "Apparel", 8, "running_apparel")] },
    ]);
    vi.spyOn(api, "prefs").mockResolvedValue({ prefs: { speech_rate_wpm: 270, received_sound: "Glass", cue_volume: 1, my_preferences: "" } } as never);
    const onOpen = vi.fn();
    renderWithCtx(<SessionsTab sessions={[]} onOpen={onOpen} />, makeCtx({ state: makeState() }));
    expect(screen.getByRole("radio", { name: /^OpenAI/ })).toBeDisabled();
    expect(await screen.findByRole("radio", { name: /^Apparel\s*8 shots/ })).toBeChecked();
    await userEvent.type(screen.getByLabelText("Name"), "Shoe day");
    await userEvent.click(screen.getByRole("radio", { name: /^Shoe review/ }));
    await userEvent.type(screen.getByLabelText("Day notes (this shoot only)"), "Overcast.");
    const follows = screen.getByTestId("coach-follows");
    expect(follows).toHaveTextContent("Project · Running blog: Soft backgrounds.");
    expect(follows).toHaveTextContent("Template · Shoe review: Laces tidy.");
    expect(follows).toHaveTextContent("This shoot: Overcast.");
    await userEvent.click(screen.getByRole("radio", { name: /^Mock/ }));
    expect(screen.getByText("Verdicts will be scripted. Labelled on every screen.", { exact: false })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("switch", { name: /Teaching mode/ }));
    await userEvent.click(screen.getByRole("radio", { name: /^Outdoor/ }));
    await userEvent.type(screen.getByLabelText("Watch folder"), "relative/path");
    expect(screen.getByText("! Use a full path, starting with / or ~")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create and start shooting" }));
    expect(create).toHaveBeenCalledWith({
      name: "Shoe day",
      product: "",
      watch_folder: "relative/path",
      assess_provider: "mock",
      template_id: "t-shoe",
      project_id: "p1",
      shoot_preferences: "Overcast.",
      teaching_mode: false,
      simulated: false,
      ui_theme: "daylight",
    });
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith("new"));
  });
});

describe("ShotListTab", () => {
  it("reorders by patching ordinals", async () => {
    const patch = vi.spyOn(api, "patchShot").mockResolvedValue({} as never);
    const ctx = makeCtx({ state: makeState() });
    renderWithCtx(<ShotListTab />, ctx);
    expect(screen.getByRole("button", { name: "Move Hero up" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Move Hero down" }));
    expect(patch).toHaveBeenCalledWith("s1", "shot-2", { ordinal: 0 });
    expect(patch).toHaveBeenCalledWith("s1", "shot-1", { ordinal: 1 });
    await waitFor(() => expect(ctx.refresh).toHaveBeenCalled());
  });

  it("edits the selected shot: must-show chips and free-text criteria", async () => {
    const patch = vi.spyOn(api, "patchShot").mockResolvedValue({} as never);
    renderWithCtx(<ShotListTab />, makeCtx({ state: makeState() }));
    await userEvent.click(screen.getByRole("button", { name: /^\d+\s*Outsole/ }));
    const form = screen.getByRole("form", { name: "Edit shot: Outsole" });
    await userEvent.click(within(form).getByRole("button", { name: "Remove mesh" }));
    await userEvent.type(within(form).getByLabelText("Add a must-show item"), "Lugs{Enter}");
    await userEvent.click(within(form).getByRole("button", { name: "Remove criterion 2" }));
    await userEvent.click(within(form).getByRole("button", { name: "+ Add criterion" }));
    await userEvent.type(within(form).getByLabelText(/Criterion 2/), "Tread pattern readable");
    expect(screen.getByText("Free text · 2–3 work best · the coach checks each one")).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("button", { name: "Save shot" }));
    expect(patch).toHaveBeenCalledWith(
      "s1",
      "shot-2",
      expect.objectContaining({
        title: "Outsole",
        must_show: ["Lugs"],
        criteria: [
          { id: "c1", text: "Mesh weave is sharp" },
          { id: expect.any(String), text: "Tread pattern readable" },
        ],
      }),
    );
  });

  it("adds a shot and selects it", async () => {
    const add = vi.spyOn(api, "addShot").mockResolvedValue({ id: "shot-9" } as never);
    renderWithCtx(<ShotListTab />, makeCtx({ state: makeState() }));
    await userEvent.click(screen.getByRole("button", { name: "+ Add shot" }));
    expect(add).toHaveBeenCalledWith("s1", { title: "Shot 4" });
  });
});

describe("SetupTab", () => {
  const revs: SetupRevisionSummary[] = [
    { ...setupRev, id: "rev-1", revision: 1, light: "flash", capture_count: 3, first_seq: 1, last_seq: 3 },
    { ...setupRev, capture_count: 2, first_seq: 4, last_seq: 5 },
  ];

  it("saves only changed fields as a new revision and lists versions", async () => {
    vi.spyOn(api, "setupRevisions").mockResolvedValue(revs);
    const patch = vi.spyOn(api, "patchSetup").mockResolvedValue(setupRev);
    const ctx = makeCtx({ state: makeState() });
    renderWithCtx(<SetupTab />, ctx);
    expect(await screen.findByText("Session start · photos #1–#3")).toBeInTheDocument();
    expect(screen.getByText("v2 · current").closest("li")).toHaveTextContent("Light type → natural · photos #4–#5");

    const save = screen.getByRole("button", { name: "Save as v3" });
    expect(save).toBeDisabled();
    const light = screen.getByRole("group", { name: "Light type" });
    await userEvent.click(within(light).getByRole("radio", { name: "Continuous" }));
    await userEvent.click(screen.getByRole("button", { name: "LED panel" }));
    expect(screen.getByText("Photos from now on are coached with v3")).toBeInTheDocument();
    await userEvent.click(save);
    expect(patch).toHaveBeenCalledWith("s1", { light: "continuous", available_equipment: ["Reflector", "LED panel"] });
    await waitFor(() => expect(ctx.refresh).toHaveBeenCalled());
  });

  it("offers exactly the backend enum values", () => {
    vi.spyOn(api, "setupRevisions").mockResolvedValue(revs);
    renderWithCtx(<SetupTab />, makeCtx({ state: makeState() }));
    const values = (group: string) =>
      within(screen.getByRole("group", { name: group }))
        .getAllByRole("radio")
        .map((r) => (r as HTMLInputElement).value);
    expect(values("Light type")).toEqual(["continuous", "flash", "natural", "mixed", "unknown"]);
    expect(values("Light position")).toEqual(["movable", "fixed_sun_or_window"]);
    expect(values("Subject movement")).toEqual(["stationary", "moving", "unknown"]);
    expect(values("Camera support")).toEqual(["tripod", "handheld"]);
    expect(values("Exposure")).toEqual(["manual", "aperture_priority", "shutter_priority", "program"]);
    expect(values("ISO")).toEqual(["manual", "auto"]);
  });

  it("falls back to the current version when the revisions endpoint is missing", async () => {
    vi.spyOn(api, "setupRevisions").mockRejectedValue(new ApiError(404, "Not Found"));
    renderWithCtx(<SetupTab />, makeCtx({ state: makeState() }));
    expect(await screen.findByText("Version history isn't available from this server.")).toBeInTheDocument();
    expect(screen.getByText("v2 · current")).toBeInTheDocument();
  });
});

describe("DiagnosticsTab", () => {
  it("shows health rows, timings, and starts a replay", async () => {
    vi.spyOn(api, "diagnostics").mockResolvedValue(makeDiag());
    const imports = vi.spyOn(api, "imports").mockResolvedValue({ replay: "stale_switch", task: "t1" });
    renderWithCtx(<DiagnosticsTab />, makeCtx({ state: makeState() }));
    const health = await screen.findByRole("list", { name: "Health" });
    expect(within(health).getByText("Microphone").closest("li")).toHaveTextContent("Check:");
    expect(within(health).getByText("Transcription").closest("li")).toHaveTextContent("OK:");
    expect(screen.getByRole("rowheader", { name: "Coach verdict (model call)" }).closest("tr")).toHaveTextContent("4.1 s");

    await userEvent.click(screen.getByRole("radio", { name: /stale_switch/ }));
    await userEvent.click(screen.getByRole("button", { name: "Start replay" }));
    expect(imports).toHaveBeenCalledWith("s1", { replay: "stale_switch" });
    expect(screen.getByTestId("replay-status")).toHaveTextContent("Replay running…");
    expect(screen.getByText("Any replay marks the session SIMULATED until it ends.")).toBeInTheDocument();
  });

  it("keeps the mock controls under Developer", async () => {
    vi.spyOn(api, "diagnostics").mockResolvedValue(makeDiag());
    const mt = vi.spyOn(api, "mockTranscript").mockResolvedValue({ queued: 1 });
    renderWithCtx(<DiagnosticsTab />, makeCtx({ state: makeState() }));
    const dev = (await screen.findByText("Developer")).closest("details")!;
    expect(dev).not.toHaveAttribute("open");
    await userEvent.click(screen.getByText("Developer"));
    await userEvent.type(within(dev).getByLabelText("Mock transcript for the next voice question"), "Why?");
    await userEvent.click(within(dev).getByRole("button", { name: "Queue transcript" }));
    expect(mt).toHaveBeenCalledWith("Why?");
    expect(within(dev).getByLabelText("Mock provider failure mode")).toBeInTheDocument();
  });

  it("counts remote presses in the button test", async () => {
    vi.spyOn(api, "diagnostics").mockResolvedValue(makeDiag());
    renderWithCtx(<DiagnosticsTab />, makeCtx({ state: makeState() }));
    const btn = screen.getByRole("button", { name: /Press your button/ });
    btn.focus();
    await userEvent.keyboard("{PageDown}");
    expect(btn).toHaveTextContent("✓ Got it");
    expect(btn).toHaveTextContent("Received “PageDown” · 1 press");
  });
});
