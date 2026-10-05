import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { CameraSettingChange, CameraSnapshot } from "../../api/types";
import { useApp, useCoachEvents } from "../../AppContext";

/** The camera as the UI sees it: the server snapshot, kept current by camera.* events, plus the last change
 *  (for the big readout). Direct control: docs/plans/camera-control.md. */

export interface CameraCtx {
  cam: CameraSnapshot | null;
  /** The newest setting change, with a counter so repeated identical values still re-trigger the readout. */
  change: (CameraSettingChange & { n: number; at: number }) | null;
  refresh: () => Promise<void>;
  /** Live view is showing: you turned it on (L) and no new photo is being reviewed. */
  live: boolean;
  /** Your choice (L). */
  setLive: (v: boolean) => void;
  /** A new photo is on screen for its verdict; live view comes back by itself (see below). */
  reviewing: string | null;
  /** When live view will come back (ms since epoch), once the countdown has started. */
  returnAt: number | null;
  /** Thirds grid over live view: on by default, remembered; "grid on/off" by voice, G at the desk. */
  grid: boolean;
  setGrid: (v: boolean) => void;
  /** The coach's suggestion was just applied (for the rail's "Applied" card). */
  applied: { display: string; at: number } | null;
  /** Bumped when + asks for the framing note again. */
  noteAt: number;
}

/** After a shot, the photo and its verdict stay up until the verdict has been spoken, plus this long; then live
 *  view returns by itself, so nobody at the camera has to press L (owner, 2026-09-29; 5 s → 2 s, 2026-10-05). */
export const REVIEW_HOLD_MS = 2000;
/** If the verdict never comes (coaching paused, analysis skipped or slow), return after this long anyway. */
export const REVIEW_MAX_MS = 45000;
/** After the verdict: if no speech follows within this long, start the hold anyway. */
const SPEECH_GRACE_MS = 8000;

const Ctx = createContext<CameraCtx | null>(null);

export function useCamera(): CameraCtx {
  return (
    useContext(Ctx) ?? {
      cam: null, change: null, refresh: async () => undefined, live: false, setLive: () => undefined, reviewing: null,
      returnAt: null, grid: true, setGrid: () => undefined, applied: null, noteAt: 0,
    }
  );
}

export const connected = (cam: CameraSnapshot | null) => cam?.state === "connected";

const GRID_KEY = "aperture-ally.live-grid";
function loadGrid(): boolean {
  try {
    return localStorage.getItem(GRID_KEY) !== "0";
  } catch {
    return true;
  }
}

export function CameraProvider({ children }: { children: ReactNode }) {
  const { toast } = useApp();
  const [cam, setCam] = useState<CameraSnapshot | null>(null);
  const [change, setChange] = useState<CameraCtx["change"]>(null);
  const [liveWanted, setLiveWanted] = useState(false);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [returnAt, setReturnAt] = useState<number | null>(null);
  const [grid, setGridState] = useState(loadGrid);
  const [applied, setApplied] = useState<CameraCtx["applied"]>(null);
  const [noteAt, setNoteAt] = useState(0);
  const setGrid = useCallback((v: boolean) => {
    setGridState(v);
    try {
      localStorage.setItem(GRID_KEY, v ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, []);
  const verdictDone = useRef(false);
  const timers = useRef<number[]>([]);
  const clearTimers = () => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
  };
  const after = (ms: number, fn: () => void) => timers.current.push(window.setTimeout(fn, ms));
  const backToLive = useCallback(() => {
    clearTimers();
    verdictDone.current = false;
    setReviewing(null);
    setReturnAt(null);
  }, []);
  const holdThenLive = () => {
    setReturnAt(Date.now() + REVIEW_HOLD_MS);
    after(REVIEW_HOLD_MS, backToLive);
  };
  const setLive = useCallback(
    (v: boolean) => {
      backToLive();
      setLiveWanted(v);
    },
    [backToLive],
  );
  useEffect(() => clearTimers, []);
  const n = useRef(0);
  const refresh = useCallback(async () => {
    try {
      setCam(await api.camera());
    } catch {
      /* the connection pill covers an unreachable server */
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  useCoachEvents((ev) => {
    const p = ev.payload as Record<string, unknown>;
    if (ev.type === "camera.state") {
      void refresh();
      if (p.state !== "connected") setLive(false);
    } else if (ev.type === "camera.setting") {
      const c = p as unknown as CameraSettingChange;
      setCam((s) => (s ? { ...s, settings: { ...s.settings, [c.setting]: { ...s.settings[c.setting], value: c.value, display: c.display } } } : s));
      if (c.source !== "camera" || c.setting !== "shutterspeed") setChange({ ...c, n: ++n.current, at: Date.now() });
      if (c.source === "remote") backToLive(); // at the camera again: show what the lens sees
    } else if (ev.type === "camera.shutter") {
      backToLive();
    } else if (ev.type === "camera.applied") {
      toast({ glyph: "✓", text: `Applied the coach's suggestion: ${String(p.display ?? "")}`, tone: "ok", source: "COACH" });
      setApplied({ display: String(p.display ?? ""), at: Date.now() });
    } else if (ev.type === "camera.readout") {
      setNoteAt(Date.now());
    } else if (ev.type === "ui.grid") {
      setGrid(Boolean(p.on));
    } else if (ev.type === "capture.ready" && liveWanted && ev.capture_id) {
      // A new photo: show it and its verdict, then come back to live view by itself.
      clearTimers();
      verdictDone.current = false;
      setReturnAt(null);
      setReviewing(ev.capture_id);
      after(REVIEW_MAX_MS, backToLive);
    } else if (reviewing && ev.capture_id === reviewing && /^analysis\.(completed|failed|skipped|cancelled)$/.test(ev.type)) {
      verdictDone.current = true;
      after(SPEECH_GRACE_MS, holdThenLive); // no speech followed
    } else if (reviewing && verdictDone.current && ev.type === "coach.speech.stopped") {
      clearTimers();
      holdThenLive();
    }
  });

  const live = liveWanted && reviewing == null;
  return (
    <Ctx.Provider value={{ cam, change, refresh, live, setLive, reviewing, returnAt, grid, setGrid, applied, noteAt }}>{children}</Ctx.Provider>
  );
}
