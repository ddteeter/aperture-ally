import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { CameraSettingChange, CameraSnapshot } from "../../api/types";
import { useApp, useCoachEvents } from "../../AppContext";

/** The camera as the UI sees it: the server snapshot, kept current by camera.* events, plus the last change
 *  (for the big readout). Direct control: docs/plans/camera-control.md. */

export interface CameraCtx {
  cam: CameraSnapshot | null;
  /** The newest setting change, with a counter so repeated identical values still re-trigger the readout. */
  change: (CameraSettingChange & { n: number }) | null;
  refresh: () => Promise<void>;
  /** Live view is on (L); photos turn it off so the new verdict shows. */
  live: boolean;
  setLive: (v: boolean) => void;
}

const Ctx = createContext<CameraCtx | null>(null);

export function useCamera(): CameraCtx {
  return useContext(Ctx) ?? { cam: null, change: null, refresh: async () => undefined, live: false, setLive: () => undefined };
}

export const connected = (cam: CameraSnapshot | null) => cam?.state === "connected";

export function CameraProvider({ children }: { children: ReactNode }) {
  const { toast } = useApp();
  const [cam, setCam] = useState<CameraSnapshot | null>(null);
  const [change, setChange] = useState<CameraCtx["change"]>(null);
  const [live, setLive] = useState(false);
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
      if (c.source !== "camera" || c.setting !== "shutterspeed") setChange({ ...c, n: ++n.current });
    } else if (ev.type === "camera.applied") {
      toast({ glyph: "✓", text: `Applied the coach's suggestion: ${String(p.display ?? "")}`, tone: "ok", source: "COACH" });
    } else if (ev.type === "capture.ready") {
      setLive(false); // a new photo: show it and its verdict
    }
  });

  return <Ctx.Provider value={{ cam, change, refresh, live, setLive }}>{children}</Ctx.Provider>;
}
