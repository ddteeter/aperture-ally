import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Debouncer, backoffMs, eventRelevance } from "./events";

const SID = "s1";

describe("eventRelevance", () => {
  it("refetches the session for its own capture/analysis/shot events", () => {
    for (const type of ["capture.ready", "capture.discovered", "analysis.completed", "analysis.failed", "shot.updated", "experiment.updated", "session.active_shot", "replay.completed"]) {
      expect(eventRelevance({ type, session_id: SID }, SID).session).toBe(true);
    }
  });
  it("ignores events for other sessions", () => {
    expect(eventRelevance({ type: "capture.ready", session_id: "other" }, SID).session).toBe(false);
  });
  it("treats session-less voice/speech events as relevant (global audio state)", () => {
    expect(eventRelevance({ type: "voice.state.changed", session_id: null }, SID).session).toBe(true);
    expect(eventRelevance({ type: "coach.speech.stopped", session_id: null }, SID).session).toBe(true);
    expect(eventRelevance({ type: "capture.ready", session_id: null }, SID).session).toBe(false);
  });
  it("ignores hello/ping/replay.log/keys.learned", () => {
    for (const type of ["hello", "ping", "replay.log", "keys.learned"]) {
      expect(eventRelevance({ type, session_id: SID }, SID)).toEqual({ session: false, sessionList: false });
    }
  });
  it("refreshes the session list on session create/update, even with no session open", () => {
    expect(eventRelevance({ type: "session.created", session_id: "new" }, null)).toEqual({ session: false, sessionList: true });
    expect(eventRelevance({ type: "session.updated", session_id: SID }, SID)).toEqual({ session: true, sessionList: true });
  });
});

describe("Debouncer", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("coalesces a burst into one trailing call after 150 ms of quiet", () => {
    const fn = vi.fn();
    const d = new Debouncer(fn, 150, 1000, () => Date.now());
    d.trigger();
    vi.advanceTimersByTime(100);
    d.trigger();
    vi.advanceTimersByTime(100);
    d.trigger();
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(149);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(d.pending).toBe(false);
  });

  it("does not starve under a continuous stream (maxWait)", () => {
    const fn = vi.fn();
    const d = new Debouncer(fn, 150, 500, () => Date.now());
    for (let i = 0; i < 20; i++) {
      d.trigger();
      vi.advanceTimersByTime(100);
    }
    expect(fn.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("cancel drops a pending call", () => {
    const fn = vi.fn();
    const d = new Debouncer(fn, 150);
    d.trigger();
    d.cancel();
    vi.advanceTimersByTime(1000);
    expect(fn).not.toHaveBeenCalled();
  });
});

describe("backoffMs", () => {
  it("grows exponentially and caps", () => {
    expect([0, 1, 2, 3].map((a) => backoffMs(a))).toEqual([500, 1000, 2000, 4000]);
    expect(backoffMs(20)).toBe(10000);
  });
});
