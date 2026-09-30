import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Capture } from "../api/types";
import { useApp, useCoachEvents } from "../AppContext";
import { usePushToTalk } from "../hooks/usePushToTalk";
import { humanize } from "../lib/format";
import { providerLabel } from "./coach/model";
import { Kbd } from "./coach/parts";
import { useKey } from "./coach/useKey";
import "./coach.css";

const TOGGLE_KEY = "aperture-ally.ptt-toggle";

export interface VoiceView {
  word: string;
  sub: string;
  glyph: string;
  color: string;
  tint: string;
}

export interface SpeechInfo {
  kind: string | null;
  captureId: string | null;
  startedAt: number;
}

const clock = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/** What the voice bar is saying about itself (glyph + word + small sub line). */
export function voiceView(o: {
  state: string;
  toggleMode: boolean;
  offline: boolean;
  transcriber: string | null | undefined;
  provider: string | null | undefined;
  speech: SpeechInfo | null;
  captures: Capture[];
  now: number;
  heldMs: number | null;
  error: string | null;
}): VoiceView {
  const ready = { glyph: "●", color: "var(--t2)", tint: "var(--raised)" };
  const acc = { color: "var(--acc)", tint: "var(--acc-t)" };
  switch (o.state) {
    case "listening": {
      const held = o.heldMs != null ? ` · ${(o.heldMs / 1000).toFixed(1)} s` : "";
      return { word: "Listening", sub: (o.toggleMode ? "Press again to send" : "Release to send") + held, glyph: "●", color: "var(--ok)", tint: "var(--ok-t)" };
    }
    case "transcribing":
      return { word: "Transcribing", sub: o.transcriber ? providerLabel(o.transcriber) : "Speech to text", glyph: "≋", color: "var(--t1)", tint: "var(--raised)" };
    case "preparing_response":
      return { word: "Thinking", sub: providerLabel(o.provider), glyph: "…", ...acc };
    case "speaking": {
      const sp = o.speech;
      const seq = sp?.captureId ? o.captures.find((c) => c.id === sp.captureId) : undefined;
      let what = "Coach";
      if (sp?.kind === "answer") what = "Answer";
      else if (sp?.kind === "notice" || sp?.kind === "cue") what = "Notice";
      else if (seq) what = `${seq.latest_assessment?.kind === "compare" ? "Comparison" : "Verdict"} #${seq.seq}`;
      const t = sp ? ` · ${clock(o.now - sp.startedAt)}` : "";
      return { word: "Speaking", sub: what + t, glyph: "◀", ...acc };
    }
    case "error":
      return { word: "Voice error", sub: o.error || "Try again", glyph: "✕", color: "var(--ret)", tint: "var(--ret-t)" };
    case "cancelled":
      return { word: "Cancelled", sub: "Mic idle", ...ready };
    default:
      if (o.offline) return { word: "Offline", sub: "Voice needs the network", glyph: "✕", color: "var(--ret)", tint: "var(--ret-t)" };
      return { word: o.state === "idle" ? "Ready" : humanize(o.state), sub: "Mic idle", ...ready };
  }
}

function useOnline() {
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine !== false));
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  return online;
}

export function VoiceBar({ captureId }: { captureId: string | null }) {
  const { sid, state, run, toast } = useApp();
  const [toggleMode, setToggleMode] = useState<boolean>(() => {
    try {
      return localStorage.getItem(TOGGLE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [liveState, setLiveState] = useState<string | null>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [listenStart, setListenStart] = useState<number | null>(null);
  const [speech, setSpeech] = useState<SpeechInfo | null>(null);
  const [lastSpoken, setLastSpoken] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const online = useOnline();
  const pressed = useRef(false);
  const ctx = useRef({ sid, captureId });
  ctx.current = { sid, captureId };

  // Authoritative voice state comes from the session snapshot; events update it immediately in between.
  const snapState = state?.voice.state ?? "idle";
  const snapAt = state?.voice.at;
  useEffect(() => {
    setLiveState(null);
  }, [snapState, snapAt]);
  useCoachEvents((ev) => {
    if (ev.type === "voice.state.changed" && typeof ev.payload.state === "string") {
      setLiveState(ev.payload.state);
      setVoiceError(ev.payload.state === "error" ? String(ev.payload.error ?? "") || null : null);
    } else if (ev.type === "coach.speech.started") {
      const p = ev.payload;
      setSpeech({ kind: typeof p.kind === "string" ? p.kind : null, captureId: ev.capture_id ?? (typeof p.capture_id === "string" ? p.capture_id : null), startedAt: Date.now() });
      if (typeof p.text === "string" && p.kind !== "cue") setLastSpoken(p.text);
    } else if (ev.type === "coach.speech.stopped") {
      setSpeech(null);
    }
  });
  const voiceState = liveState ?? snapState;
  const listening = voiceState === "listening";
  const speaking = voiceState === "speaking";

  useEffect(() => {
    if (listening) setListenStart((s) => s ?? Date.now());
    else setListenStart(null);
    if (!listening && !speaking) return;
    const t = setInterval(() => setNow(Date.now()), listening ? 100 : 500);
    return () => clearInterval(t);
  }, [listening, speaking]);

  const report = useCallback((r: Record<string, unknown> | undefined) => {
    if (r && typeof r.error === "string") setVoiceError(r.error);
  }, []);

  const start = useCallback(() => {
    if (pressed.current) return;
    pressed.current = true;
    setVoiceError(null);
    void run("Start listening", () => api.voiceStart({ session_id: ctx.current.sid, capture_id: ctx.current.captureId })).then(report);
  }, [run, report]);
  const stop = useCallback(() => {
    if (!pressed.current) return;
    pressed.current = false;
    void run("Stop listening", () => api.voiceStop({})).then(report);
  }, [run, report]);
  const toggle = useCallback(() => {
    setVoiceError(null);
    void run("Toggle listening", () => api.voiceToggle({ session_id: ctx.current.sid, capture_id: ctx.current.captureId })).then(report);
  }, [run, report]);
  const cancel = useCallback(() => {
    pressed.current = false;
    void run("Cancel", () => api.voiceCancel());
  }, [run]);
  const repeat = useCallback(async () => {
    try {
      await api.coachRepeat();
    } catch (e) {
      // Nothing said yet is normal (e.g. right after a restart): say so quietly rather than as an error.
      if (e instanceof ApiError && e.status === 404) toast({ glyph: "↻", text: "Nothing to repeat yet", tone: "neutral" });
      else void run("Repeat advice", () => Promise.reject(e));
    }
  }, [run, toast]);
  const stopVoice = useCallback(() => void run("Stop voice", () => api.coachStop()), [run]);

  usePushToTalk({ onStart: start, onStop: stop, onToggle: toggle, onCancel: cancel }, { enabled: !!sid, toggleMode });
  useKey({ key: "r" }, repeat, !!sid);
  useKey({ key: "s" }, stopVoice, !!sid);

  const provider = state?.session.assess_provider;
  const offline = !online || (!!provider && state?.provider_health?.[provider]?.ok === false);
  const turn = state?.voice.turn;
  const v = voiceView({
    state: voiceState,
    toggleMode,
    offline,
    transcriber: state?.voice.transcriber,
    provider,
    speech,
    captures: state?.captures ?? [],
    now,
    heldMs: listenStart ? now - listenStart : null,
    error: voiceError ?? turn?.error ?? null,
  });
  const you = turn?.transcript ? `“${turn.transcript}”` : "—";
  const coach = turn?.answer ?? lastSpoken ?? "—";
  const pttLabel = toggleMode ? (listening ? "Click to send" : "Click to talk") : listening ? "Release to send" : "Hold to talk";

  return (
    <section className="vb" aria-labelledby="voice-h" data-testid="voice-bar">
      <h2 id="voice-h" className="cp-sr">
        Ask the coach
      </h2>
      <button
        type="button"
        className={`vb-ptt${listening ? " is-on" : ""}`}
        style={{ background: v.tint }}
        data-ptt-key-target
        data-testid="ptt"
        aria-label={`${pttLabel}. Voice: ${v.word}, ${v.sub}`}
        aria-pressed={toggleMode ? listening : undefined}
        disabled={!sid}
        onPointerDown={(e) => {
          if (toggleMode || e.button !== 0) return;
          e.preventDefault();
          start();
        }}
        onPointerUp={() => !toggleMode && stop()}
        onPointerLeave={() => !toggleMode && stop()}
        onPointerCancel={() => !toggleMode && stop()}
        onContextMenu={(e) => e.preventDefault()}
        onClick={() => {
          if (toggleMode) toggle();
        }}
      >
        <span className="vb-dot" style={{ color: v.color }} aria-hidden="true">
          {v.glyph}
        </span>
        <span className="vb-mode" aria-hidden="true">
          <span className="vb-word" style={{ color: v.color }}>
            {v.word}
          </span>
          <span className="vb-sub">{v.sub}</span>
        </span>
      </button>
      <p className="cp-sr" role="status" data-testid="voice-state">
        Voice: {v.word}. {v.sub}
      </p>

      <dl className="vb-lines">
        <dt>You</dt>
        <dd data-testid="voice-transcript">{you}</dd>
        <dt>Coach</dt>
        <dd aria-live="polite" data-testid="voice-answer">
          {coach}
        </dd>
      </dl>

      <div className="vb-actions">
        <button type="button" className="cp-btn cp-btn-s" onClick={repeat} disabled={!sid}>
          Repeat <Kbd>R</Kbd>
        </button>
        <button type="button" className="cp-btn cp-btn-s" onClick={stopVoice} disabled={!sid}>
          Stop voice <Kbd>S</Kbd>
        </button>
        <label className="vb-toggle" title="Click (or press Space) once to start and again to send, instead of holding">
          <input
            type="checkbox"
            checked={toggleMode}
            onChange={(e) => {
              setToggleMode(e.target.checked);
              try {
                localStorage.setItem(TOGGLE_KEY, e.target.checked ? "1" : "0");
              } catch {
                /* ignore */
              }
            }}
          />
          Toggle
        </label>
        <span className="vb-hint">
          {toggleMode ? "Press" : "Hold"} <Kbd>Space</Kbd> to talk · remote: L talk, R pause, B cancel
        </span>
      </div>
    </section>
  );
}
