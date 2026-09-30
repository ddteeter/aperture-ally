import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionState } from "../api/types";
import { makeCtx, renderWithCtx } from "../test/ctx";
import { makeCapture, sessionState } from "../test/fixtures";
import { VoiceBar, voiceView } from "./VoiceBar";

afterEach(() => vi.restoreAllMocks());

const base = { toggleMode: false, offline: false, transcriber: "openai", provider: "claude", speech: null, captures: [], now: 0, heldMs: null, error: null };

describe("voiceView", () => {
  it("names each state with a glyph and a word", () => {
    expect(voiceView({ ...base, state: "idle" })).toMatchObject({ word: "Ready", sub: "Mic idle" });
    expect(voiceView({ ...base, state: "listening", heldMs: 1200 })).toMatchObject({ word: "Listening", sub: "Release to send · 1.2 s" });
    expect(voiceView({ ...base, state: "transcribing" })).toMatchObject({ word: "Transcribing", sub: "OpenAI" });
    expect(voiceView({ ...base, state: "transcribing", transcriber: "mock" })).toMatchObject({ sub: "Mock" });
    expect(voiceView({ ...base, state: "preparing_response" })).toMatchObject({ word: "Thinking", sub: "Claude" });
    expect(voiceView({ ...base, state: "idle", offline: true })).toMatchObject({ word: "Offline", sub: "Voice needs the network" });
  });

  it("says what is being spoken and for how long", () => {
    const c = makeCapture("cap-12", 12);
    const v = voiceView({ ...base, state: "speaking", captures: [c], speech: { kind: "advice", captureId: "cap-12", startedAt: 1000 }, now: 7500 });
    expect(v).toMatchObject({ word: "Speaking", sub: "Verdict #12 · 0:06" });
  });

  it("never claims transcription is on-device", () => {
    expect(voiceView({ ...base, state: "transcribing", transcriber: undefined }).sub).not.toMatch(/device/i);
  });
});

function renderBar(extra: Partial<SessionState> = {}) {
  const c = makeCtx({ state: sessionState(extra) });
  renderWithCtx(<VoiceBar captureId="cap-2" />, c);
  return c;
}

describe("VoiceBar", () => {
  it("shows the last YOU / COACH lines", () => {
    const st = sessionState();
    renderBar({
      voice: {
        ...st.voice,
        turn: { id: "v1", session_id: "s1", shot_id: null, capture_id: null, voice_epoch: 1, started_at: "", duration_s: 1, transcript: "Is the logo sharp?", intent: "question", answer: "Yes, it reads well.", status: "done", error: null, audio_path: null, timings: {} },
      },
    });
    expect(screen.getByTestId("voice-state")).toHaveTextContent("Voice: Ready");
    expect(screen.getByTestId("voice-transcript")).toHaveTextContent("“Is the logo sharp?”");
    expect(screen.getByTestId("voice-answer")).toHaveTextContent("Yes, it reads well.");
  });

  it("shows Offline when the coach provider is unreachable", () => {
    renderBar({ provider_health: { claude: { ok: false, at: "", error: "no network" } } });
    expect(screen.getByTestId("voice-state")).toHaveTextContent("Offline");
  });

  it("Repeat / Stop via buttons and R / S keys, but not while typing", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("{}"));
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: /Repeat/ }));
    fireEvent.keyDown(window, { key: "s" });
    await vi.waitFor(() => expect(f).toHaveBeenCalledTimes(2));
    expect(f.mock.calls.map(([u]) => u)).toEqual(["/api/coach/repeat", "/api/coach/stop"]);

    render(<input aria-label="note" />);
    fireEvent.keyDown(screen.getByLabelText("note"), { key: "r" });
    fireEvent.keyDown(window, { key: "r", metaKey: true });
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("holds Space to talk and releases to send", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("{}"));
    renderBar();
    fireEvent.keyDown(window, { key: " ", code: "Space" });
    fireEvent.keyUp(window, { key: " ", code: "Space" });
    await vi.waitFor(() => expect(f).toHaveBeenCalledTimes(2));
    expect(f.mock.calls.map(([u]) => u)).toEqual(["/api/voice/start", "/api/voice/stop"]);
    expect(JSON.parse(String(f.mock.calls[0][1]?.body))).toMatchObject({ session_id: "s1", capture_id: "cap-2" });
  });
});

describe("Repeat with nothing said yet", () => {
  it("is a quiet notice, not an error", async () => {
    const { ApiError, api } = await import("../api/client");
    vi.spyOn(api, "coachRepeat").mockRejectedValue(new ApiError(404, "nothing spoken yet"));
    const c = makeCtx({ state: sessionState(), run: vi.fn() as never });
    renderWithCtx(<VoiceBar captureId="cap-2" />, c);
    fireEvent.click(screen.getByRole("button", { name: /Repeat/ }));
    await vi.waitFor(() => expect(c.toast).toHaveBeenCalledWith(expect.objectContaining({ text: "Nothing to repeat yet" })));
    expect(c.run).not.toHaveBeenCalled();
  });
});
