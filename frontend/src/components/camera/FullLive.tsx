import { useEffect, useState } from "react";
import { api, imageUrl } from "../../api/client";
import type { DeviceSummary, Shot } from "../../api/types";
import { useApp, useCoachEvents } from "../../AppContext";
import { useShortcuts } from "../../lib/keys";
import { verdictMeta } from "../../ui/status";
import { verdictKind } from "../coach/model";
import { connected, useCamera } from "./CameraContext";
import { LiveImg, Readout } from "./CameraViews";
import "./fulllive.css";

/** Full-screen live view (docs/design/Aperture Ally Live View.dc.html, brief 3): the picture 4:3 at full height,
 *  flush left, one settings rail on the right, and overlays for the shot, the coach and the verdict. The normal
 *  Shoot layout stays mounted underneath, so push-to-talk and the other keys keep working. */

const NOTE_MS = 6000; // framing note after opening, a shot change, or +
const HOT_MS = 3000; // the last-changed setting stays in accent
const COACH_SHRINK_MS = 8000; // the coach line shrinks this long after speech ends
const APPLIED_MS = 3000;

function useNow(every = 250) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), every);
    return () => clearInterval(t);
  }, [every]);
  return now;
}

/** Voice state and the coach's line, from the snapshot plus live events (same sources as the voice bar). */
function useCoachLine() {
  const { state } = useApp();
  const [liveState, setLiveState] = useState<string | null>(null);
  const [line, setLine] = useState<string | null>(null);
  const [spokeAt, setSpokeAt] = useState<number | null>(null);
  const snap = state?.voice.state ?? "idle";
  useEffect(() => setLiveState(null), [snap, state?.voice.at]);
  useCoachEvents((ev) => {
    const p = ev.payload as Record<string, unknown>;
    if (ev.type === "voice.state.changed" && typeof p.state === "string") setLiveState(p.state);
    else if (ev.type === "coach.speech.started" && typeof p.text === "string" && p.kind !== "camera" && p.kind !== "cue") {
      setLine(p.text);
      setSpokeAt(null);
    } else if (ev.type === "coach.speech.stopped") setSpokeAt(Date.now());
  });
  const voice = liveState ?? snap;
  return { voice, line: line ?? state?.voice.turn?.answer ?? null, question: state?.voice.turn?.transcript ?? null, spokeAt };
}

function useDevices(): DeviceSummary | null {
  const [d, setD] = useState<DeviceSummary | null>(null);
  useEffect(() => {
    let alive = true;
    const poll = () => api.devices().then((x) => alive && setD(x)).catch(() => undefined);
    void poll();
    const t = setInterval(poll, 3000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  return d;
}

const RAIL: { key: string; label: string; hint: string }[] = [
  { key: "aperture", label: "APERTURE", hint: "↑↓" },
  { key: "shutterspeed", label: "SHUTTER", hint: "A-mode" },
  { key: "iso", label: "ISO", hint: "ZL ZR" },
  { key: "exposurecompensation", label: "COMP", hint: "←→" },
];

/** "Heel fills the right third. Must show: logo, pull tab." */
export function framingNote(shot: Shot): string {
  const f = shot.framing.trim();
  const framing = f && !/[.!?]$/.test(f) ? `${f}.` : f;
  const must = shot.must_show.length ? `Must show: ${shot.must_show.join(", ")}.` : "";
  return [framing, must].filter(Boolean).join(" ");
}

export function FullLive({ onExit }: { onExit: () => void }) {
  const { state } = useApp();
  const { cam, change, reviewing, returnAt, grid, setGrid, applied, noteAt } = useCamera();
  const now = useNow();
  const coach = useCoachLine();
  const devices = useDevices();
  const [sug, setSug] = useState<{ setting: string; value: string; display: string } | null>(null);
  const [noteFrom, setNoteFrom] = useState(() => Date.now());
  const activeShot: Shot | null = state?.shots.find((s) => s.id === state.session.active_shot_id) ?? null;
  const latestSeq = state ? Math.max(0, ...state.captures.map((c) => c.seq)) : 0;

  useEffect(() => setNoteFrom(Date.now()), [activeShot?.id]);
  useEffect(() => {
    if (noteAt) setNoteFrom(noteAt);
  }, [noteAt]);
  useEffect(() => {
    api.cameraSuggestion().then(setSug).catch(() => setSug(null));
  }, [latestSeq, applied?.at]);
  useShortcuts((s) => {
    if (s.kind === "escape") {
      onExit();
      return true;
    }
    return false;
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "g" && !e.metaKey && !e.ctrlKey && !e.altKey && (e.target as HTMLElement)?.tagName !== "INPUT") {
        setGrid(!grid);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [grid, setGrid]);

  if (!cam || !state) return null;
  const on = connected(cam);
  const shotIndex = activeShot ? state.shots.findIndex((s) => s.id === activeShot.id) + 1 : 0;
  const showNote = activeShot && now - noteFrom < NOTE_MS && (activeShot.framing || activeShot.must_show.length);
  const recent = change && change.source !== "camera" ? now - change.at : Infinity;
  const hotKey = recent < HOT_MS ? change!.setting : null;
  const readoutUp = recent < 1500; // the big readout is showing: keep the coach box out of its way
  const review = reviewing ? state.captures.find((c) => c.id === reviewing) ?? null : null;
  const issues: { t: string; s: string }[] = [];
  if (devices?.mic.state === "none") issues.push({ t: "Mic unavailable", s: "Talk (L) is off until a mic is back." });
  if (devices?.mic.state === "fallback") issues.push({ t: "Mic on the Mac", s: "AirPods not available. Talk (L) uses the Mac's mic." });
  if (devices?.remote.state === "asleep") issues.push({ t: "Remote asleep", s: "Press any button on the 8BitDo to wake it." });
  const honesty = [state.session.simulated && "SIMULATED", state.session.assess_provider === "mock" && "MOCK PROVIDER", cam.mode === "mock" && "SIMULATED CAMERA"].filter(Boolean) as string[];
  const appliedRecent = applied && now - applied.at < APPLIED_MS;

  return (
    <div className="fl" role="dialog" aria-label="Live view, full screen" data-testid="full-live">
      <div className="fl-pic">
        {!on ? (
          <div className="fl-asleep">
            <span className="fl-asleep-g">◎</span>
            <span className="fl-asleep-t">{cam.state === "asleep" ? "Camera asleep" : cam.state === "busy_elsewhere" ? "OM Capture has the camera" : "Waiting for the camera"}</span>
            <span className="fl-asleep-s">
              {cam.state === "asleep"
                ? "Half-press the shutter on the E-M1 to wake it. Live view comes back by itself."
                : cam.state === "busy_elsewhere"
                  ? "Quit OM Capture to control the camera from here."
                  : "Plug in USB and switch the E-M1 on. Live view starts by itself."}
            </span>
          </div>
        ) : review ? (
          <img
            key={review.evidence?.available ? "overview" : "original"}
            className="fl-img"
            // The overview exists once the photo is measured; until then show the JPEG as it arrived.
            src={imageUrl(review.id, review.evidence?.available ? "overview" : "original")}
            alt={`Photo #${review.seq}`}
          />
        ) : (
          <LiveImg className="fl-img" />
        )}

        {on && !review && grid && (
          <div className="fl-grid" aria-hidden="true" data-testid="live-grid">
            <span style={{ left: "33.333%" }} className="v" />
            <span style={{ left: "66.666%" }} className="v" />
            <span style={{ top: "33.333%" }} className="h" />
            <span style={{ top: "66.666%" }} className="h" />
          </div>
        )}

        {on && activeShot && (
          <div className="fl-shot">
            <span className="fl-eyebrow">
              SHOT {shotIndex} OF {state.shots.length}
            </span>
            <span className="fl-shot-name">{activeShot.title}</span>
            {showNote && (
              <span className="fl-shot-note" data-testid="framing-note">
                {framingNote(activeShot)}
              </span>
            )}
          </div>
        )}

        {on && (
          <span className="fl-tag">
            {review ? (
              `PHOTO #${review.seq}`
            ) : (
              <>
                <span className="fl-dot" aria-hidden="true" />
                LIVE
              </>
            )}
          </span>
        )}

        <Readout />

        {on && !review && <CoachBox coach={coach} now={now} hidden={readoutUp} />}
        {on && review && <VerdictBox captureId={review.id} returnAt={returnAt} now={now} />}
      </div>

      <aside className="fl-rail" aria-label="Camera settings">
        {issues.length > 0 && (
          <div role="alert" className="fl-issues">
            {issues.map((i) => (
              <div key={i.t} className="fl-issue">
                <span className="fl-issue-t">{i.t}</span>
                <span className="fl-issue-s">{i.s}</span>
              </div>
            ))}
          </div>
        )}
        {RAIL.map((r) => {
          const isHot = hotKey === r.key;
          const v = (cam.settings[r.key]?.display ?? "—").replace(/^ISO /, "");
          return (
            <div key={r.key} className={isHot ? "fl-set is-hot" : "fl-set"} data-testid={`rail-${r.key}`}>
              <span className="fl-set-head">
                <span>{r.label}</span>
                <span className="fl-t3">{r.hint}</span>
              </span>
              <span className="fl-set-val">{v}</span>
              {sug && sug.setting === r.key && !appliedRecent && <span className="fl-set-sug">→ {sug.display}</span>}
            </div>
          );
        })}
        <div className="fl-grow" />
        {appliedRecent ? (
          <div className="fl-applied">
            <span className="fl-eyebrow-r">✓ APPLIED</span>
            <span className="fl-card-t">{applied!.display} set on the camera</span>
          </div>
        ) : (
          sug && (
            <div className="fl-sug">
              <span className="fl-eyebrow-r">COACH SUGGESTS</span>
              <span className="fl-card-t">Set {sug.display}</span>
              <span className="fl-sug-y">
                <span className="fl-y">Y</span>applies
              </span>
            </div>
          )
        )}
        {honesty.map((h) => (
          <span key={h} className="fl-honesty">
            {h}
          </span>
        ))}
        <span className="fl-exit">
          <span className="fl-mono">L</span> or <span className="fl-mono">Esc</span> exits · <span className="fl-mono">G</span> grid
        </span>
      </aside>
    </div>
  );
}

function CoachBox({ coach, now, hidden }: { coach: ReturnType<typeof useCoachLine>; now: number; hidden: boolean }) {
  if (hidden) return null;
  const v = coach.voice;
  const vs =
    v === "speaking"
      ? { g: "▮▮▮", word: "SPEAKING", sub: "· R pauses", cls: "is-acc" }
      : v === "listening"
        ? { g: "◉", word: "LISTENING", sub: "· let go of L to send", cls: "is-acc" }
        : v === "transcribing" || v === "preparing_response"
          ? { g: "⋯", word: "THINKING", sub: "", cls: "" }
          : { g: "●", word: "COACH", sub: "· X repeats", cls: "" };
  const busy = v === "speaking" || v === "listening" || v === "transcribing" || v === "preparing_response";
  const text =
    v === "listening" ? "Listening…" : v === "transcribing" || v === "preparing_response" ? (coach.question ? `“${coach.question}”` : "…") : coach.line;
  if (!text) return null;
  const big = busy || (coach.spokeAt != null && now - coach.spokeAt < COACH_SHRINK_MS);
  return (
    <div className="fl-coach" data-testid="live-coach">
      <span className={`fl-coach-state ${vs.cls}`}>
        <span className="fl-coach-g">{vs.g}</span>
        {vs.word}
        <span className="fl-coach-sub">{vs.sub}</span>
      </span>
      <span className={big ? "fl-coach-big" : "fl-coach-small"}>{text}</span>
    </div>
  );
}

function VerdictBox({ captureId, returnAt, now }: { captureId: string; returnAt: number | null; now: number }) {
  const { state } = useApp();
  const c = state?.captures.find((x) => x.id === captureId);
  const la = c?.latest_assessment;
  const r = la?.status === "completed" ? la.result : null;
  const meta = r ? verdictMeta(r.verdict) : null;
  const kind = r ? verdictKind(r) : null;
  const word = kind === "usable" ? "Usable" : kind === "usable_but" ? "Usable, but…" : meta?.word;
  const line = r ? r.primary_action?.instruction ?? r.spoken_text : la?.status === "failed" ? "The coach couldn't review this one." : null;
  const secs = returnAt ? Math.max(0, Math.ceil((returnAt - now) / 1000)) : null;
  return (
    <div className="fl-verdict" data-testid="live-verdict">
      <div className="fl-verdict-main">
        {r && meta ? (
          <span className="fl-verdict-head">
            <span className="fl-verdict-tile" style={{ background: meta.tint, color: meta.color }}>
              {meta.glyph}
            </span>
            <span className="fl-verdict-word" style={{ color: meta.color }}>
              {word}
            </span>
          </span>
        ) : (
          <span className="fl-verdict-head">
            <span className="fl-verdict-tile fl-analysing">…</span>
            <span className="fl-verdict-word">{la?.status === "failed" ? "No verdict" : c ? `Analysing #${c.seq}` : "New photo"}</span>
          </span>
        )}
        {line && <span className="fl-verdict-line">{line}</span>}
      </div>
      <div className="fl-verdict-count">
        <span className="fl-count">{secs != null ? `${secs} s` : "…"}</span>
        <span className="fl-count-sub">{secs != null ? "to live view · any button now" : "live view after the verdict · any button now"}</span>
      </div>
    </div>
  );
}
