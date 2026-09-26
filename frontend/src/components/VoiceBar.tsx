import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { useApp, useCoachEvents } from "../AppContext";
import { usePushToTalk } from "../hooks/usePushToTalk";
import { humanize } from "../lib/format";

const STATE_TEXT: Record<string, string> = {
  idle: "Idle — hold to ask a question",
  listening: "Listening…",
  transcribing: "Transcribing…",
  preparing_response: "Preparing answer…",
  speaking: "Speaking",
  cancelled: "Cancelled",
  error: "Error",
};

const TOGGLE_KEY = "photo-coach.ptt-toggle";

export function VoiceBar({ captureId }: { captureId: string | null }) {
  const { sid, state, run } = useApp();
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
  const [now, setNow] = useState(Date.now());
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
    }
  });
  const voiceState = liveState ?? snapState;

  useEffect(() => {
    if (voiceState === "listening") {
      setListenStart((s) => s ?? Date.now());
      const t = setInterval(() => setNow(Date.now()), 100);
      return () => clearInterval(t);
    }
    setListenStart(null);
    return undefined;
  }, [voiceState]);

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

  usePushToTalk({ onStart: start, onStop: stop, onToggle: toggle, onCancel: cancel }, { enabled: !!sid, toggleMode });

  const turn = state?.voice.turn;
  const held = listenStart ? ((now - listenStart) / 1000).toFixed(1) : null;
  const listening = voiceState === "listening";

  return (
    <section className="voice-bar" aria-labelledby="voice-h" data-testid="voice-bar">
      <h2 id="voice-h" className="sr-only">
        Ask the coach
      </h2>
      <button
        type="button"
        className={listening ? "ptt ptt-on" : "ptt"}
        data-ptt-key-target
        data-testid="ptt"
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
        {toggleMode ? (listening ? "Click to stop" : "Click to talk") : listening ? "Release to send" : "Hold to talk"}
      </button>
      <div className="voice-info">
        <p className="voice-state" role="status" data-testid="voice-state">
          <strong>Voice: {STATE_TEXT[voiceState] ?? humanize(voiceState)}</strong>
          {held && <span className="hold-timer"> · held {held}s</span>}
          {voiceError && <span className="error-text"> · {voiceError}</span>}
        </p>
        {turn?.transcript && (
          <p className="small" data-testid="voice-transcript">
            <strong>You:</strong> “{turn.transcript}”
          </p>
        )}
        {turn?.answer && (
          <p className="small" aria-live="polite" data-testid="voice-answer">
            <strong>Coach:</strong> {turn.answer}
          </p>
        )}
        {turn?.error && <p className="small error-text">Voice error: {turn.error}</p>}
        <p className="tiny muted">
          Space: hold to talk (when not typing) · Esc: cancel. The global Bluetooth-remote key works even when the
          browser isn't focused (configured in the backend).
        </p>
      </div>
      <div className="voice-controls">
        <label className="check">
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
          Toggle mode
        </label>
        <button type="button" onClick={cancel}>
          Cancel (Esc)
        </button>
      </div>
    </section>
  );
}
