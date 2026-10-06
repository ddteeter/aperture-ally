import { useEffect, useRef, useState } from "react";
import { api, CAMERA_LIVE_URL } from "../../api/client";
import type { CameraSettingChange, CameraSnapshot } from "../../api/types";
import { useApp } from "../../AppContext";
import { connected, useCamera } from "./CameraContext";
import "./camera.css";

/** Direct camera control on the Shoot screen (Shoot v2 · group 6): live view, the big readout, the camera panel
 *  and the release dialog. */

const LABEL: Record<string, string> = { aperture: "APERTURE", exposurecompensation: "EXPOSURE COMP.", iso: "ISO", shutterspeed: "SHUTTER" };
const KEY: Record<string, string> = { aperture: "↑ ↓", exposurecompensation: "← →", iso: "ZL ZR", shutterspeed: "A-mode" };
const READOUT_MS = 1500;

function num(v: string): number | null {
  const n = Number.parseFloat(v);
  return Number.isFinite(n) ? n : null;
}

/** Whole stops get the taller tick: f/2, 2.8, 4, 5.6 …; whole EV; ISO 100, 200, 400 … */
export function isFullStop(setting: string, v: string): boolean {
  const n = num(v);
  if (n == null) return false;
  if (setting === "aperture") return [1, 1.4, 2, 2.8, 4, 5.6, 8, 11, 16, 22, 32].includes(Math.round(n * 10) / 10);
  if (setting === "exposurecompensation") return Math.abs(n - Math.round(n)) < 0.05;
  if (setting === "iso") return Number.isInteger(Math.log2(n / 100));
  return false;
}

function display(setting: string, v: string | undefined): string {
  if (!v) return "—";
  if (setting === "aperture") return `f/${num(v) ?? v}`;
  if (setting === "iso") return v.toLowerCase() === "auto" ? "Auto" : v;
  return v;
}

/** The big value in the middle of the stage while you change a setting; fades 1.5 s after the last change. */
export function Readout() {
  const { cam, change } = useCamera();
  const [shown, setShown] = useState<(CameraSettingChange & { n: number; at: number }) | null>(null);
  useEffect(() => {
    if (!change || change.setting === "shutterspeed" || change.source === "camera") return;
    setShown(change);
    const t = window.setTimeout(() => setShown(null), READOUT_MS);
    return () => window.clearTimeout(t);
  }, [change]);
  if (!shown || !cam) return null;
  const order = cam.settings[shown.setting]?.order ?? [];
  const i = order.indexOf(shown.value);
  const status = shown.end
    ? `▕ ${shown.end} · end of range`
    : shown.source === "coach"
      ? shown.clamped
        ? "! the lens stops here"
        : "✓ applied"
      : `${KEY[shown.setting] ?? ""} to change`;
  return (
    <div className="cam-readout" aria-hidden="true" data-testid="camera-readout">
      <span className="cam-readout-label">
        {LABEL[shown.setting]}
        {shown.source === "coach" ? " · COACH’S SUGGESTION" : ""}
      </span>
      <span className="cam-readout-value">{shown.setting === "aperture" ? shown.display : shown.display.replace(/^ISO /, "")}</span>
      {order.length > 1 && (
        <div className="cam-ticks">
          {order.map((v, j) => (
            <span
              key={v}
              className={j === i ? "cam-tick is-cur" : j === 0 || j === order.length - 1 ? "cam-tick is-end" : "cam-tick"}
              style={{ height: j === i ? 26 : isFullStop(shown.setting, v) ? 16 : 9 }}
            />
          ))}
        </div>
      )}
      <div className="cam-readout-foot">
        <span>{display(shown.setting, order[0])}</span>
        <span className="cam-bold">{status}</span>
        <span>{display(shown.setting, order[order.length - 1])}</span>
      </div>
    </div>
  );
}

/** The live-view stream. Each connection gets its own URL: after the camera slept and reconnected, the web view
 *  kept showing the old stream's last frame (same URL, no new request) — a still image (desk, 2026-10-05). A
 *  dropped stream retries after a second. */
let streamSeq = 0; // unique for the page's lifetime, so a remount never reuses an old stream's URL
const nextStream = () => ++streamSeq;

export function LiveImg({ className }: { className: string }) {
  const { cam } = useCamera();
  const [token, setToken] = useState(nextStream);
  const isOn = connected(cam);
  useEffect(() => {
    if (isOn) setToken(nextStream());
  }, [isOn]);
  const retry = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(retry.current), []);
  return (
    <img
      className={className}
      src={`${CAMERA_LIVE_URL}?s=${token}`}
      alt="Live view from the camera"
      onError={() => {
        window.clearTimeout(retry.current);
        retry.current = window.setTimeout(() => setToken(nextStream()), 1000);
      }}
    />
  );
}

function settingLine(cam: CameraSnapshot) {
  const s = cam.settings;
  return [s.aperture?.display, s.shutterspeed?.display, s.iso?.display, s.exposurecompensation?.display].filter(Boolean) as string[];
}

/** The stage in live-view mode: the camera's live view with its settings along the bottom, or what to do. */
export function CameraStage() {
  const { cam, change } = useCamera();
  const [hot, setHot] = useState<string | null>(null);
  useEffect(() => {
    if (!change || change.source === "camera") return;
    setHot(change.setting);
    const t = window.setTimeout(() => setHot(null), READOUT_MS);
    return () => window.clearTimeout(t);
  }, [change]);
  if (!cam) return null;
  if (!connected(cam)) {
    const [title, sub, meta] =
      cam.state === "asleep"
        ? ["Camera asleep", "Half-press the shutter to wake it. Remote camera buttons pause until then; L, R and B still work.", cam.detail]
        : cam.state === "busy_elsewhere"
          ? ["OM Capture has the camera", "Quit OM Capture to control the camera from here. Its photos still arrive through the watch folder.", cam.detail]
          : cam.state === "released"
            ? ["Camera released", "OM Capture can use it. Press ⌘K to take control again.", "Photos from OM Capture still arrive through the watch folder"]
            : cam.state === "off"
              ? ["Camera control is off", "Set APERTURE_ALLY_CAMERA=direct to control the camera from here.", "Photos still arrive through the watch folder"]
              : ["Waiting for the camera", "Plug in USB and switch the E-M1 on. Photos from OM Capture still arrive through the watch folder.", "Looking for a camera on USB · every 2 s"];
    return (
      <div className="cam-offline" data-testid="camera-offline">
        <span className="cam-offline-g">◎</span>
        <span className="cam-offline-title">{title}</span>
        <span className="cam-offline-sub">{sub}</span>
        <span className="cam-offline-meta">{meta}</span>
      </div>
    );
  }
  const vals = settingLine(cam);
  const keys = ["aperture", "shutterspeed", "iso", "exposurecompensation"];
  return (
    <div className="cam-live" data-testid="camera-live">
      <div className="cam-live-inner">
      <div className="cam-live-frame">
        <LiveImg className="cam-live-img" />
        <span className="cam-live-tag">
          <span className="cam-live-dot" aria-hidden="true" />
          LIVE
        </span>
        <div className="cam-live-bar">
          {vals.map((v, i) => (
            <span key={i} className={hot === keys[i] ? "is-hot" : undefined}>
              {v}
            </span>
          ))}
        </div>
      </div>
      </div>
    </div>
  );
}

const REMOTE: [string, string][] = [
  ["L", "Hold to talk"],
  ["A", "Shutter"],
  ["R", "Pause coaching"],
  ["+", "Read settings"],
  ["B", "Cancel"],
  ["Y", "Apply suggestion"],
  ["↑ ↓", "Aperture ⅓"],
  ["← →", "Exp. comp. ⅓"],
  ["ZL ZR", "ISO ⅓"],
  ["X", "Repeat advice"],
];

/** The coach panel in camera mode: connection, the settings with their remote buttons, the suggestion, the legend. */
export function CameraPanel({ onRelease }: { onRelease: () => void }) {
  const { cam, change } = useCamera();
  const { run, toast, state } = useApp();
  const [sug, setSug] = useState<{ display: string } | null>(null);
  const latest = state ? Math.max(0, ...state.captures.map((c) => c.seq)) : 0;
  useEffect(() => {
    api.cameraSuggestion().then(setSug).catch(() => setSug(null));
  }, [latest, change?.source === "coach" ? change.n : 0]);
  if (!cam) return null;
  const on = connected(cam);
  const conn = on
    ? { state: "Connected · you control it", sub: cam.detail, cls: "is-ok", btn: "Release camera" }
    : cam.state === "released"
      ? { state: "Released to OM Capture", sub: "Take it back any time", cls: "", btn: "Take control" }
      : { state: cam.state === "asleep" ? "Camera asleep" : cam.state === "busy_elsewhere" ? "OM Capture has it" : "Waiting for camera", sub: cam.detail, cls: "is-unc", btn: "Take control" };
  const apply = () =>
    run("Apply the suggestion", async () => {
      const r = await api.cameraApply();
      toast({ glyph: "✓", text: r.text, tone: "ok", source: "KEYBOARD" });
    });
  return (
    <section className="cam-panel" aria-label="Camera" data-testid="camera-panel">
      <div className={`cam-conn ${conn.cls}`}>
        <span className="cam-conn-g" aria-hidden="true">◎</span>
        <span className="cam-conn-text">
          <span className="cam-conn-state">{conn.state}</span>
          <span className="cam-conn-sub">{conn.sub}</span>
        </span>
        <button type="button" className="cam-btn" aria-keyshortcuts="Meta+K" onClick={on ? onRelease : () => void run("Take control", () => api.cameraTake())}>
          {conn.btn} <span className="cam-kbd">⌘K</span>
        </button>
      </div>
      <div className={on ? "cam-grid" : "cam-grid is-off"}>
        {(["aperture", "exposurecompensation", "shutterspeed", "iso"] as const).map((k) => (
          <div key={k} className={change?.setting === k && change.source !== "camera" ? "cam-cell is-hot" : "cam-cell"}>
            <span className="cam-cell-head">
              <span>{{ aperture: "Aperture", exposurecompensation: "Exposure comp.", shutterspeed: "Shutter", iso: "ISO" }[k]}</span>
              <span className="cam-mono">{KEY[k]}</span>
            </span>
            <span className="cam-cell-val">{(cam.settings[k]?.display ?? "—").replace(/^ISO /, "")}</span>
          </div>
        ))}
      </div>
      {on && sug && (
        <div className="cam-sug">
          <span className="cam-eyebrow">COACH’S SUGGESTION{latest ? ` FOR #${latest}` : ""}</span>
          <span className="cam-sug-text">Set {sug.display}.</span>
          <button type="button" className="cam-btn cam-btn-pri" aria-keyshortcuts="Y" onClick={() => void apply()}>
            Apply {sug.display} <span className="cam-kbd">Y</span>
          </button>
        </div>
      )}
      <div className="cam-remote">
        <span className="cam-eyebrow">REMOTE</span>
        <div className="cam-remote-grid">
          {REMOTE.map(([k, d]) => (
            <span key={k} className="cam-remote-row">
              <span className="cam-mono cam-t1">{k}</span>
              <span>{d}</span>
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

/** "Release the camera to OM Capture?" — lists exactly what stops and what keeps working. */
export function ReleaseDialog({ onClose }: { onClose: () => void }) {
  const { run } = useApp();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("button")?.focus();
    return () => prev?.focus?.();
  }, []);
  return (
    <div className="cam-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        className="cam-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Release the camera"
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Escape") {
            e.preventDefault();
            onClose();
          }
        }}
      >
        <div className="cam-stack-6">
          <span className="cam-dialog-title">Release the camera to OM Capture?</span>
          <span className="cam-dialog-lede">Only one app can control the E-M1 at a time.</span>
        </div>
        <ul className="cam-dialog-list">
          <li>Live view stops here.</li>
          <li>D-pad, A, Y, ZL/ZR and + stop controlling the camera. L, R and B keep working.</li>
          <li>Photos you take in OM Capture still arrive through the watch folder and get coached.</li>
          <li>The camera's own buttons stay locked until you unplug it and plug it back in (it does this after any PC control, OM Capture's too).</li>
        </ul>
        <div className="cam-dialog-actions">
          <button
            type="button"
            className="cam-btn cam-btn-pri cam-btn-l"
            onClick={() =>
              run("Release camera", async () => {
                await api.cameraRelease();
                onClose();
              })
            }
          >
            Release camera
          </button>
          <button type="button" className="cam-btn cam-btn-l" onClick={onClose}>
            Keep control <span className="cam-kbd">Esc</span>
          </button>
          <span className="cam-dialog-note">Take it back any time with ⌘K</span>
        </div>
      </div>
    </div>
  );
}
