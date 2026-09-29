import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { ModelCallView, Project } from "../api/types";
import { makeCtx, renderWithCtx } from "../test/ctx";
import { sessionState } from "../test/fixtures";
import { CoachSaw } from "./coach/CoachSaw";
import { LibraryTab } from "./LibraryTab";
import { ShootOriginBar, TodayNotes, shotMarks } from "./ShootTemplate";

afterEach(() => vi.restoreAllMocks());

const project = (over: Partial<Project> = {}): Project => ({
  id: "p1", name: "Running blog", preferences: "Soft backgrounds.", archived: false, created_at: "", updated_at: "",
  shoot_count: 5, last_used: null,
  templates: [
    { id: "t-shoe", project_id: "p1", name: "Shoe review", preferences: "", version: 2, source: "running_shoe", archived: false,
      created_at: "", updated_at: "", shot_count: 6, shot_titles: ["Hero (3/4 lateral)", "Outsole"], shoot_count: 5, last_used: null,
      history: [] },
  ],
  ...over,
});

describe("Library", () => {
  it("saves your defaults on blur and says it's used from the next photo", async () => {
    localStorage.removeItem("aperture-ally.library");
    vi.spyOn(api, "projects").mockResolvedValue([project()]);
    vi.spyOn(api, "prefs").mockResolvedValue({ prefs: { my_preferences: "" } } as never);
    const patchPrefs = vi.spyOn(api, "patchPrefs").mockResolvedValue({ prefs: { my_preferences: "Lightroom." } } as never);
    renderWithCtx(<LibraryTab onNewShoot={vi.fn()} />, makeCtx());
    expect(await screen.findByText("Empty is fine. Most people leave this blank for weeks.")).toBeInTheDocument();
    const mine = screen.getByLabelText("Your defaults");
    await userEvent.type(mine, "Lightroom.");
    fireEvent.blur(mine);
    expect(patchPrefs).toHaveBeenCalledWith({ my_preferences: "Lightroom." });
    expect(await screen.findByText(/Saved · used from the next photo/)).toBeInTheDocument();
  });

  it("edits a project's look, duplicates a template from the menu, and asks before archiving", async () => {
    localStorage.setItem("aperture-ally.library", JSON.stringify({ kind: "project", id: "p1" }));
    vi.spyOn(api, "projects").mockResolvedValue([project()]);
    vi.spyOn(api, "prefs").mockResolvedValue({ prefs: { my_preferences: "" } } as never);
    const patchProject = vi.spyOn(api, "patchProject").mockResolvedValue(project());
    const createTemplate = vi.spyOn(api, "createTemplate").mockResolvedValue({ id: "t-new" } as never);
    vi.spyOn(api, "template").mockResolvedValue(new Promise(() => undefined) as never);
    const onNewShoot = vi.fn();
    renderWithCtx(<LibraryTab onNewShoot={onNewShoot} />, makeCtx());
    const look = await screen.findByLabelText("Running blog: the look");
    await userEvent.clear(look);
    await userEvent.type(look, "Warm light.");
    fireEvent.blur(look);
    expect(patchProject).toHaveBeenCalledWith("p1", { preferences: "Warm light." });
    const row = screen.getByTestId("template-Shoe review");
    expect(row).toHaveTextContent("Shoe review");
    expect(row).toHaveTextContent("v2");
    await userEvent.click(screen.getByRole("button", { name: "Archive…" }));
    expect(screen.getByRole("alertdialog", { name: "Archive project" })).toHaveTextContent("stop appearing in New shoot");
    expect(patchProject).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: /^New shoot ⌘N$/ }));
    expect(onNewShoot).toHaveBeenCalledWith({ projectId: "p1" });
    await userEvent.click(within(row).getByRole("button", { name: "Duplicate Shoe review" }));
    const menu = screen.getByRole("dialog", { name: "New template" });
    await userEvent.type(within(menu).getByLabelText("New template name"), "Trail shoe review{Enter}");
    expect(createTemplate).toHaveBeenCalledWith("p1", { name: "Trail shoe review", copy_from: "t-shoe" });
  });

  it("edits a template's shots as a draft and saves them as the next version", async () => {
    localStorage.setItem("aperture-ally.library", JSON.stringify({ kind: "template", id: "t-shoe" }));
    vi.spyOn(api, "projects").mockResolvedValue([project()]);
    vi.spyOn(api, "prefs").mockResolvedValue({ prefs: { my_preferences: "" } } as never);
    const full = {
      id: "t-shoe", project_id: "p1", name: "Shoe review", preferences: "", version: 2, source: null, archived: false,
      created_at: "", updated_at: "",
      history: [{ version: 2, at: "2026-09-12T10:00:00Z", how: "from_shoot", session_id: "s", session_name: "Pegasus 41", summary: "Added Heel counter" }],
      shots: [{ title: "Hero", purpose: "", must_show: ["Logo"], framing: "Low ¾", criteria: [{ id: "c1", text: "Sharp" }], sharp_regions: [] }],
    };
    vi.spyOn(api, "template").mockResolvedValue(full as never);
    const patch = vi.spyOn(api, "patchTemplate").mockResolvedValue({ ...full, version: 3 } as never);
    renderWithCtx(<LibraryTab onNewShoot={vi.fn()} />, makeCtx());
    expect(await screen.findByText(/Updated from Pegasus 41/)).toBeInTheDocument();
    expect(screen.getByText("Added Heel counter")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "+ Add criterion" }));
    await userEvent.type(screen.getByLabelText("Criterion 2"), "Laces tidy");
    await userEvent.click(screen.getByRole("button", { name: "Save as v3" }));
    expect(patch).toHaveBeenCalledWith("t-shoe", {
      shots: [expect.objectContaining({ criteria: [{ id: "c1", text: "Sharp" }, { id: expect.any(String), text: "Laces tidy" }] })],
    });
  });

  it("shows where a shoot came from, what changed, and saves to its template only after confirming", async () => {
    vi.spyOn(api, "projects").mockResolvedValue([project()]);
    const save = vi.spyOn(api, "saveToTemplate").mockResolvedValue({ name: "Shoe review", version: 3 } as never);
    const st = sessionState();
    st.session = { ...st.session, project_id: "p1", template_id: "t-shoe", template_version: 2, shoot_preferences: "Overcast." };
    st.origin = {
      project_id: "p1", project_name: "Running blog", template_id: "t-shoe", template_name: "Shoe review", template_version: 2,
      template_current_version: 2, saved: null,
      changes: [
        { g: "~", title: "2 · Outsole", detail: "Criterion added: “Lugs sharp”" },
        { g: "+", title: "3 · Laces detail", detail: "New shot · 0 criteria" },
      ],
    };
    const c = makeCtx({ state: st });
    renderWithCtx(<><ShootOriginBar /><TodayNotes /></>, c);
    expect(screen.getByRole("button", { name: "Running blog › Shoe review v2" })).toBeInTheDocument();
    expect(screen.getByTestId("today-notes")).toHaveTextContent("Overcast.");
    await userEvent.click(screen.getByRole("button", { name: /2 shots changed · Save…/ }));
    const dlg = screen.getByRole("dialog", { name: "Save changes to Shoe review" });
    expect(dlg).toHaveTextContent("v2 to v3");
    expect(within(dlg).getByRole("list", { name: "Changes" })).toHaveTextContent("Laces detail");
    expect(dlg).toHaveTextContent("Not saved: today's notes (“Overcast.”) stay with this shoot.");
    expect(save).not.toHaveBeenCalled();
    await userEvent.click(within(dlg).getByRole("button", { name: "Save as v3" }));
    expect(save).toHaveBeenCalledWith(st.session.id);
    expect(c.toast).toHaveBeenCalledWith(expect.objectContaining({ text: "Saved to Shoe review · v3" }));
  });

  it("saves as a new template instead, and edits today's notes with N", async () => {
    vi.spyOn(api, "projects").mockResolvedValue([project()]);
    const save = vi.spyOn(api, "saveToTemplate").mockResolvedValue({ name: "Trail shoe review", version: 1 } as never);
    const patch = vi.spyOn(api, "patchSession").mockResolvedValue({} as never);
    const st = sessionState();
    st.origin = {
      project_id: "p1", project_name: "Running blog", template_id: "t-shoe", template_name: "Shoe review", template_version: 2,
      template_current_version: 2, saved: null, changes: [{ g: "+", title: "3 · Laces detail", detail: "New shot" }],
    };
    renderWithCtx(<><ShootOriginBar /><TodayNotes /></>, makeCtx({ state: st }));
    await userEvent.click(screen.getByRole("button", { name: /1 shot changed · Save…/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save as new template instead" }));
    const dlg = screen.getByRole("dialog", { name: "Save as a new template" });
    await userEvent.type(within(dlg).getByLabelText("Name"), "Trail shoe review");
    await userEvent.click(within(dlg).getByRole("button", { name: "Create “Trail shoe review”" }));
    expect(save).toHaveBeenCalledWith(st.session.id, "Trail shoe review", "p1");

    fireEvent.keyDown(window, { key: "n" });
    const pop = await screen.findByRole("dialog", { name: "Today's notes" });
    const box = within(pop).getByLabelText("Today's notes");
    await userEvent.type(box, "Sun breaking through.");
    fireEvent.keyDown(box, { key: "Enter", metaKey: true });
    expect(patch).toHaveBeenCalledWith(st.session.id, { shoot_preferences: "Sun breaking through." });
  });

  it("marks shots that differ from the template", () => {
    expect([...shotMarks([
      { g: "~", title: "4 · Heel counter", detail: "Criterion added: “Pull tab”" },
      { g: "+", title: "7 · Laces detail", detail: "New shot" },
      { g: "−", title: "Old shot", detail: "Removed" },
    ])]).toEqual([[4, "◆ edited: +1 criterion"], [7, "◆ added in this shoot"]]);
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
