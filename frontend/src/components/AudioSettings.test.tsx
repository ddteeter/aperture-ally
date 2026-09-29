import { act, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AudioPrefsView, DeviceSummary } from "../api/types";
import { micChip, remoteChip, transitionToast } from "./DeviceChips";
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
  it("labels speed in wpm and podcast-style multiples (180 wpm = 1×)", () => {
    expect(rateLabel(270)).toBe("270 wpm ≈ 1.5×");
    expect(rateLabel(180)).toBe("180 wpm ≈ 1×");
    expect(rateLabel(300)).toBe("300 wpm ≈ 1.65×");
  });

  it("shows the saved speed, saves a new one after the slider settles, and previews it", async () => {
    const f = mockApi();
    renderWithCtx(<AudioSettings />, makeCtx());
    const slider = await screen.findByRole("slider", { name: "Speech speed" });
    expect(slider).toHaveAttribute("aria-valuetext", "270 words per minute, about 1.5 times");
    vi.useFakeTimers();
    fireEvent.change(slider, { target: { value: "300" } });
    expect(slider).toHaveAttribute("aria-valuetext", "300 words per minute, about 1.65 times");
    await act(async () => {
      vi.advanceTimersByTime(400);
    });
    vi.useRealTimers();
    await vi.waitFor(() => expect(calls(f)).toContain('PATCH /api/prefs {"speech_rate_wpm":300}'));
    await userEvent.click(screen.getByRole("button", { name: /Hear the speed/ }));
    await vi.waitFor(() => expect(calls(f)).toContain('POST /api/prefs/preview {"what":"speech"}'));
    expect(screen.getByRole("button", { name: /Speaking at 1.65×/ })).toBeInTheDocument();
  });

  it("changes the received sound and its volume, and plays it over speech", async () => {
    const f = mockApi();
    renderWithCtx(<AudioSettings />, makeCtx());
    const sounds = await screen.findByRole("radiogroup", { name: "“Photo received” sound" });
    expect(within(sounds).getByRole("radio", { name: "Glass" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(within(sounds).getByRole("radio", { name: "Ping" }));
    fireEvent.change(screen.getByRole("slider", { name: "Volume" }), { target: { value: "2" } });
    await userEvent.click(screen.getByRole("button", { name: /Hear it over speech/ }));
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

describe("device chips", () => {
  const dev = (mic: DeviceSummary["mic"]["state"], remote: DeviceSummary["remote"]["state"]): DeviceSummary => ({
    mic: { state: mic, device: mic === "fallback" ? "MacBook Air Microphone" : "Drew’s AirPods Pro", preferred: "Drew’s AirPods Pro", detail: "d" },
    remote: { state: remote, detail: "r", reconnects: 0 },
  });

  it("are quiet glyphs when all is well and labelled chips when something changed", () => {
    expect(micChip(dev("ok", "ok").mic, false)).toMatchObject({ label: "", tone: "quiet" });
    expect(micChip(dev("fallback", "ok").mic, false)).toMatchObject({ label: "Mac mic", tone: "unc" });
    expect(micChip(dev("none", "ok").mic, false)).toMatchObject({ glyph: "✕", label: "No mic", tone: "ret" });
    expect(micChip(dev("ok", "ok").mic, true)).toMatchObject({ label: "AirPods Pro", tone: "ok" });
    expect(remoteChip(dev("ok", "asleep").remote, false)).toMatchObject({ label: "Remote asleep", tone: "unc" });
    expect(remoteChip(dev("ok", "off").remote, false)).toBeNull();
  });

  it("explain each change once with a toast", () => {
    expect(transitionToast(dev("ok", "ok"), dev("fallback", "ok"))[0].text).toMatch(/^Mic moved to MacBook Air Microphone/);
    expect(transitionToast(dev("fallback", "ok"), dev("ok", "ok"))[0].text).toBe("Back on AirPods Pro");
    expect(transitionToast(dev("ok", "ok"), dev("ok", "asleep"))[0].text).toMatch(/Space still works as talk/);
    expect(transitionToast(dev("ok", "ok"), dev("ok", "ok"))).toEqual([]);
  });
});
