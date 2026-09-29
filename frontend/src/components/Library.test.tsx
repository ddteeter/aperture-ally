import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { ModelCallView, Project } from "../api/types";
import { makeCtx, renderWithCtx } from "../test/ctx";
import { sessionState } from "../test/fixtures";
import { CoachSaw } from "./coach/CoachSaw";
import { LibraryPanel, ShootOrigin } from "./Library";

afterEach(() => vi.restoreAllMocks());

const project = (over: Partial<Project> = {}): Project => ({
  id: "p1", name: "Running blog", preferences: "Soft backgrounds.", archived: false, created_at: "", updated_at: "",
  templates: [
    { id: "t-shoe", project_id: "p1", name: "Shoe review", preferences: "", version: 2, source: "running_shoe", archived: false,
      created_at: "", updated_at: "", shot_count: 6, shot_titles: ["Hero (3/4 lateral)", "Outsole"] },
  ],
  ...over,
});

describe("Library", () => {
  it("saves your defaults and a project's look on blur, and duplicates a template", async () => {
    vi.spyOn(api, "projects").mockResolvedValue([project()]);
    vi.spyOn(api, "prefs").mockResolvedValue({ prefs: { my_preferences: "" } } as never);
    const patchPrefs = vi.spyOn(api, "patchPrefs").mockResolvedValue({ prefs: { my_preferences: "Lightroom." } } as never);
    const patchProject = vi.spyOn(api, "patchProject").mockResolvedValue(project());
    const createTemplate = vi.spyOn(api, "createTemplate").mockResolvedValue({} as never);
    renderWithCtx(<LibraryPanel />, makeCtx());
    const mine = await screen.findByLabelText("Your defaults (all projects)");
    await userEvent.type(mine, "Lightroom.");
    fireEvent.blur(mine);
    expect(patchPrefs).toHaveBeenCalledWith({ my_preferences: "Lightroom." });
    const look = screen.getByLabelText("Running blog: the project's look");
    await userEvent.clear(look);
    await userEvent.type(look, "Warm light.");
    fireEvent.blur(look);
    expect(patchProject).toHaveBeenCalledWith("p1", { preferences: "Warm light." });
    const row = screen.getByTestId("template-Shoe review");
    expect(row).toHaveTextContent("6 shots · v2");
    await userEvent.click(within(row).getByRole("button", { name: /Duplicate/ }));
    await userEvent.type(within(row).getByLabelText("New template name"), "Trail shoe review");
    await userEvent.click(within(row).getByRole("button", { name: "Create copy" }));
    expect(createTemplate).toHaveBeenCalledWith("p1", { name: "Trail shoe review", copy_from: "t-shoe" });
  });

  it("shows where a shoot came from and saves to its template only after confirming", async () => {
    vi.spyOn(api, "projects").mockResolvedValue([project()]);
    const save = vi.spyOn(api, "saveToTemplate").mockResolvedValue({ name: "Shoe review", version: 3 } as never);
    const st = sessionState();
    st.session = { ...st.session, project_id: "p1", template_id: "t-shoe", template_version: 2, shoot_preferences: "Overcast." };
    renderWithCtx(<ShootOrigin />, makeCtx({ state: st }));
    expect(await screen.findByText("Running blog › Shoe review · v2")).toBeInTheDocument();
    expect(screen.getByLabelText("Day notes (this shoot only)")).toHaveValue("Overcast.");
    await userEvent.click(screen.getByRole("button", { name: "Save to template" }));
    expect(save).not.toHaveBeenCalled();
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Save as v3" }));
    expect(save).toHaveBeenCalledWith(st.session.id);
  });
});

describe("What the coach saw", () => {
  it("lists the preferences, metadata, images and instructions sent", async () => {
    const call: ModelCallView = {
      id: "m1", purpose: "assess", attempt: 0, provider: "claude", model_requested: "claude-sonnet-5-5",
      model_resolved: "claude-sonnet-5-5", prompt_version: "coach-2026-09-28.2", status: "ok", latency_ms: 9600,
      usage: { input_tokens: 7041, output_tokens: 1118 }, validation_errors: [],
      request: {
        instructions: "Judge it on two levels.",
        context: { preferences: { yours: null, project: "Soft backgrounds.", template: null, shoot: "Overcast." },
                   metadata: { f_number: 8, iso: 6400 }, capture: { raw_kept: true, basis: "RAW paired with this photo" } },
        images: [{ role: "current", kind: "overview", region_id: "whole_image", label: "current photo, full frame" }],
      },
      response_text: '{"verdict":"usable_candidate"}',
    };
    vi.spyOn(api, "assessmentCalls").mockResolvedValue([call]);
    const onClose = vi.fn();
    renderWithCtx(<CoachSaw assessmentId="a1" captureId="c1" onClose={onClose} />, makeCtx());
    const sec = await screen.findByTestId("saw-call");
    expect(sec).toHaveTextContent("claude-sonnet-5-5 · prompt coach-2026-09-28.2 · 9.6 s · in/out 7041/1118 tokens");
    expect(sec).toHaveTextContent("project: Soft backgrounds.");
    expect(sec).toHaveTextContent("shoot: Overcast.");
    expect(sec).toHaveTextContent("f_number: 8 · iso: 6400 · RAW kept: yes");
    expect(sec.querySelector("img")).toHaveAttribute("src", expect.stringContaining("/captures/c1/image/overview"));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});
