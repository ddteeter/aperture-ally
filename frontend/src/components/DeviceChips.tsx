import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { DeviceSummary } from "../api/types";
import type { CameraSnapshot } from "../api/types";
import { useApp, type ToastInput } from "../AppContext";
import { useCamera } from "./camera/CameraContext";

/** Mic and remote in the top bar (Shoot v2 · group 5). When all is well they are small grey glyphs with a
 *  tooltip; on a change the glyph grows into a labelled chip and a toast explains it once. After a device
 *  comes back, its chip says so for 5 s, then shrinks back to the glyph. */

const POLL_MS = 3000;
const BACK_MS = 5000;

type Tone = "quiet" | "unc" | "ret" | "ok";
export interface ChipView {
  key: "mic" | "remote" | "camera";
  glyph: string;
  label: string;
  title: string;
  tone: Tone;
}

export function micChip(m: DeviceSummary["mic"], back: boolean): ChipView {
  if (m.state === "fallback") return { key: "mic", glyph: "◉", label: "Mac mic", title: m.detail, tone: "unc" };
  if (m.state === "none") return { key: "mic", glyph: "✕", label: "No mic", title: m.detail, tone: "ret" };
  if (m.state === "stalled") return { key: "mic", glyph: "◉", label: "Mic silent", title: m.detail, tone: "unc" };
  if (back) return { key: "mic", glyph: "◉", label: short(m.device), title: m.detail, tone: "ok" };
  return { key: "mic", glyph: "◉", label: "", title: m.detail, tone: "quiet" };
}

export function remoteChip(r: DeviceSummary["remote"], back: boolean): ChipView | null {
  if (r.state === "off" || r.state === "keyboard") return null;
  if (r.state === "asleep") return { key: "remote", glyph: "▣", label: "Remote asleep", title: r.detail, tone: "unc" };
  if (back) return { key: "remote", glyph: "▣", label: "Remote back", title: r.detail, tone: "ok" };
  return { key: "remote", glyph: "▣", label: "", title: r.detail, tone: "quiet" };
}

/** The camera: quiet "You control" while connected; a chip when it's waiting, asleep or held elsewhere. */
export function cameraChip(cam: CameraSnapshot | null): ChipView | null {
  if (!cam || cam.mode === "off") return null;
  const c = (label: string, tone: Tone) => ({ key: "camera" as const, glyph: "◎", label, title: cam.detail, tone });
  switch (cam.state) {
    case "connected":
      return c("You control", "quiet");
    case "connecting":
      return c("Connecting…", "quiet");
    case "asleep":
      return c("Camera asleep", "unc");
    case "busy_elsewhere":
      return c("OM Capture", "quiet");
    case "released":
      return c("Released", "quiet");
    default:
      return c("Waiting for camera", "unc");
  }
}

/** "Drew’s AirPods Pro" → "AirPods Pro"; the chip only needs the device type. */
function short(name: string | null): string {
  if (!name) return "Mic back";
  const m = /AirPods[^,]*/.exec(name);
  return m ? m[0] : name.length > 18 ? `${name.slice(0, 17)}…` : name;
}

/** The one toast for a transition, or null when the change doesn't need one. */
export function transitionToast(prev: DeviceSummary, next: DeviceSummary): ToastInput[] {
  const out: ToastInput[] = [];
  const pm = prev.mic.state;
  const nm = next.mic.state;
  if (pm !== nm) {
    if (nm === "fallback")
      out.push({ glyph: "◉", text: `Mic moved to ${next.mic.device ?? "the Mac"}. Hold L to talk as before; it switches back when you wear them.`, tone: "unc", source: "MIC" });
    else if (nm === "none") out.push({ glyph: "✕", text: "No microphone. Voice is off; coaching and speech still work.", tone: "ret", source: "MIC" });
    else if (nm === "ok" && (pm === "fallback" || pm === "none" || pm === "stalled"))
      out.push({ glyph: "◉", text: `Back on ${short(next.mic.device)}`, tone: "ok", source: "MIC" });
  }
  const pr = prev.remote.state;
  const nr = next.remote.state;
  if (pr !== nr) {
    if (nr === "asleep") out.push({ glyph: "▣", text: "Remote is asleep. Press any button to wake it. Space still works as talk.", tone: "unc", source: "REMOTE" });
    else if (nr === "ok" && pr === "asleep") out.push({ glyph: "▣", text: "Remote connected", tone: "ok", source: "REMOTE" });
  }
  return out;
}

export function DeviceChips() {
  const { toast } = useApp();
  const { cam } = useCamera();
  const [d, setD] = useState<DeviceSummary | null>(null);
  const [back, setBack] = useState<{ mic: boolean; remote: boolean }>({ mic: false, remote: false });
  const prev = useRef<DeviceSummary | null>(null);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const next = await api.devices();
        if (!alive) return;
        const p = prev.current;
        if (p) {
          for (const t of transitionToast(p, next)) toast(t);
          const returned = {
            mic: p.mic.state !== "ok" && next.mic.state === "ok",
            remote: p.remote.state === "asleep" && next.remote.state === "ok",
          };
          for (const k of ["mic", "remote"] as const) {
            if (!returned[k]) continue;
            setBack((b) => ({ ...b, [k]: true }));
            clearTimeout(timers.current[k]);
            timers.current[k] = setTimeout(() => setBack((b) => ({ ...b, [k]: false })), BACK_MS);
          }
        }
        prev.current = next;
        setD(next);
      } catch {
        /* the connection pill already says when the server is unreachable */
      }
    };
    void poll();
    const t = setInterval(() => void poll(), POLL_MS);
    const own = timers.current;
    return () => {
      alive = false;
      clearInterval(t);
      for (const x of Object.values(own)) clearTimeout(x);
    };
  }, [toast]);

  const chips = [d && micChip(d.mic, back.mic), d && remoteChip(d.remote, back.remote), cameraChip(cam)].filter(
    (c): c is ChipView => !!c,
  );
  if (!chips.length) return null;
  return (
    <div className="dev-chips" role="status" aria-live="polite" data-testid="devices">
      {chips.map((c) => (
        <span key={c.key} className={`dev-chip dev-${c.tone}`} title={c.title} aria-label={c.title}>
          <span className="mono" aria-hidden="true">
            {c.glyph}
          </span>
          {c.label}
        </span>
      ))}
    </div>
  );
}
