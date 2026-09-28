import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AudioPrefsView } from "../api/types";
import { shortcutFor } from "../lib/keys";
import { makeCtx, renderWithCtx } from "../test/ctx";
import { AudioSettings, rateLabel } from "./ShootStatus";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const view = (over: Partial<AudioPrefsView["prefs"]> = {}): AudioPrefsView => ({
  prefs: { speech_rate_wpm: 270, received_sound: "Glass", cue_volume: 1, ...over },
  defaults: { speech_rate_wpm: 190, received_sound: "Pop", cue_volume: 1 },
  sounds: ["Glass", "Ping", "Pop"],
  speech_rate_range: [120, 400],
  cue_volume_range: [0.25, 4],
  received_cue: "sound",
  speech_backend: "say",
});

function mockApi() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    if (String(url).endsWith("/prefs/preview")) return new Response(JSON.stringify({ playing: body.what }));
    if (init?.method === "PATCH") return new Response(JSON.stringify(view(body)));
    return new Response(JSON.stringify(view()));
  });
}
const calls = (f: ReturnType<typeof mockApi>) =>
  f.mock.calls.map(([u, i]) => `${i?.method ?? "GET"} ${u} ${i?.body ?? ""}`.trim());

describe("audio settings", () => {
  it("labels speed in wpm and podcast-style multiples", () => {
    expect(rateLabel(270)).toBe("270 wpm · ≈1.5×");
    expect(rateLabel(180)).toBe("180 wpm · ≈1.0×");
  });

  it("shows the saved speed, saves a new one after the slider settles, and previews it", async () => {
    const f = mockApi();
    renderWithCtx(<AudioSettings />, makeCtx());
    const slider = await screen.findByRole("slider");
    expect(screen.getByText("270 wpm · ≈1.5×")).toBeInTheDocument();
    vi.useFakeTimers();
    fireEvent.change(slider, { target: { value: "300" } });
    expect(screen.getByText("300 wpm · ≈1.7×")).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(400);
    });
    vi.useRealTimers();
    await vi.waitFor(() => expect(calls(f)).toContain('PATCH /api/prefs {"speech_rate_wpm":300}'));
    await userEvent.click(screen.getByRole("button", { name: /Hear the speed/ }));
    await vi.waitFor(() => expect(calls(f)).toContain('POST /api/prefs/preview {"what":"speech"}'));
  });

  it("changes the received sound and its volume, and plays it over speech", async () => {
    const f = mockApi();
    renderWithCtx(<AudioSettings />, makeCtx());
    await userEvent.selectOptions(await screen.findByLabelText("Received sound"), "Ping");
    await userEvent.selectOptions(screen.getByLabelText("Received sound volume"), "Loud");
    await userEvent.click(screen.getByRole("button", { name: /sound over speech/ }));
    await vi.waitFor(() =>
      expect(calls(f)).toEqual(
        expect.arrayContaining([
          'PATCH /api/prefs {"received_sound":"Ping"}',
          'PATCH /api/prefs {"cue_volume":2}',
          'POST /api/prefs/preview {"what":"mix"}',
        ]),
      ),
    );
  });

  it("arrow keys on a slider move the slider, not the filmstrip", () => {
    const range = Object.assign(document.createElement("input"), { type: "range" });
    expect(shortcutFor({ key: "ArrowRight", target: range, metaKey: false, ctrlKey: false, altKey: false })).toBeNull();
    expect(shortcutFor({ key: "ArrowRight", target: document.body, metaKey: false, ctrlKey: false, altKey: false })).toEqual({
      kind: "step",
      dir: 1,
    });
  });
});
