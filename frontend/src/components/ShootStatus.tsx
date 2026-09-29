import { type RefObject, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { AudioPrefs, AudioPrefsView, Capture } from "../api/types";
import { useApp } from "../AppContext";
import { shotTitle } from "../lib/format";
import { useShortcuts } from "../lib/keys";

/** How long "Received #N" stays on the stage after a capture.ready event. */
export const RECEIVED_MS = 6000;

function readySeconds(c: Capture | undefined): string | null {
  if (!c?.detected_at || !c.ready_at) return null;
  const s = (Date.parse(c.ready_at) - Date.parse(c.detected_at)) / 1000;
  return Number.isFinite(s) && s >= 0 ? `${s.toFixed(1)} s` : null;
}

/**
 * "✓ Received #N" over the stage: confirms the backend has the file before Drew switches shots.
 * The live region is always mounted so the arrival is announced; the visible card fades after a few seconds.
 */
export function ReceivedOverlay() {
  const { state, received } = useApp();
  const [fresh, setFresh] = useState(false);
  useEffect(() => {
    if (!received) return;
    const left = RECEIVED_MS - (Date.now() - received.at);
    if (left <= 0) return;
    setFresh(true);
    const t = window.setTimeout(() => setFresh(false), left);
    return () => window.clearTimeout(t);
  }, [received]);
  if (!state) return null;
  const cap = received ? state.captures.find((c) => c.id === received.captureId) : undefined;
  const other = received && received.shotId !== state.session.active_shot_id;
  const secs = readySeconds(cap);
  return (
    <div className="received-wrap" data-testid="received">
      <p className="sr-only" role="status" aria-live="polite">
        {received ? `Received photo #${received.seq} for ${shotTitle(state.shots, received.shotId)}.` : ""}
        {received?.ambiguous ? " Shot attribution uncertain." : ""}
      </p>
      {received && fresh && (
        <div className="received-card" aria-hidden="true">
          <span className="glyph tone-ok">✓</span>
          <span className="received-title">Received #{received.seq}</span>
          {secs && <span className="received-secs mono">{secs}</span>}
          {(other || received.ambiguous) && (
            <span className="received-sub">
              {received.ambiguous ? "shot uncertain · " : "for "}
              {shotTitle(state.shots, received.shotId)}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Closes a popover on Escape or a click outside `ref`; focus returns to `returnTo`.
 * An open popover owns Esc: it listens in the capture phase and stops the event, so the
 * window-level Esc handlers underneath (cancel analysis, cancel speech/recording) don't also fire.
 */
export function useDismiss(open: boolean, close: () => void, ref: RefObject<HTMLElement | null>, returnTo?: RefObject<HTMLElement | null>) {
  const cb = useRef(close);
  cb.current = close;
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopImmediatePropagation();
      cb.current();
      returnTo?.current?.focus();
    };
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) cb.current();
    };
    window.addEventListener("keydown", onKey, true);
    document.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open, ref, returnTo]);
}

const CUE_TEXT: Record<string, string> = {
  sound: "Sound: the received sound above plays when a new photo arrives.",
  speech: "Spoken: says “Received twelve” in your headphones.",
  none: "None: silent. Watch for the on-screen “Received” message.",
};

export function usageLine(calls: number | null, cap: number | null, cost: number | null): string {
  const c = calls == null ? "—" : String(calls);
  return `${cap != null ? `${c} / ${cap}` : c} calls · ≈ $${(cost ?? 0).toFixed(2)}`;
}

/** 1× ≈ conversational speech; shown so podcast listeners can think in their usual speed. */
const NORMAL_WPM = 180;

export function speedX(wpm: number): string {
  return String(Math.round((wpm / NORMAL_WPM) * 20) / 20);
}

export function rateLabel(wpm: number): string {
  return `${wpm} wpm ≈ ${speedX(wpm)}×`;
}

/** Speech speed and the received sound, applied live and saved per person (not per shoot). */
export function AudioSettings() {
  const { run } = useApp();
  const [view, setView] = useState<AudioPrefsView | null>(null);
  const [wpm, setWpm] = useState<number | null>(null);
  const [vol, setVol] = useState<number | null>(null);
  const [playing, setPlaying] = useState<"speech" | "mix" | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const volTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const playTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .prefs()
      .then((v) => {
        if (!alive) return;
        setView(v);
        setWpm(v.prefs.speech_rate_wpm);
        setVol(v.prefs.cue_volume);
      })
      .catch(() => alive && setView(null));
    return () => {
      alive = false;
      for (const t of [timer, volTimer, playTimer]) if (t.current) clearTimeout(t.current);
    };
  }, []);

  if (!view || wpm == null || vol == null) return <p className="pop-note">Loading audio settings…</p>;
  const [lo, hi] = view.speech_rate_range;
  const [vlo, vhi] = view.cue_volume_range;
  const save = async (body: Partial<AudioPrefs>) => {
    const r = await run("Save audio settings", () => api.patchPrefs(body));
    if (r) setView(r);
    return r;
  };
  const onRate = (v: number) => {
    setWpm(v);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void save({ speech_rate_wpm: v }), 350);
  };
  const onVol = (v: number) => {
    setVol(v);
    if (volTimer.current) clearTimeout(volTimer.current);
    volTimer.current = setTimeout(() => void save({ cue_volume: v }), 350);
  };
  const hear = async (what: "speech" | "mix") => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
      if (wpm !== view.prefs.speech_rate_wpm) await save({ speech_rate_wpm: wpm });
    }
    if (volTimer.current) {
      clearTimeout(volTimer.current);
      volTimer.current = null;
      if (vol !== view.prefs.cue_volume) await save({ cue_volume: vol });
    }
    setPlaying(what);
    if (playTimer.current) clearTimeout(playTimer.current);
    // The sample sentence is ~20 words: long enough to judge, then the button settles back.
    playTimer.current = setTimeout(() => setPlaying(null), Math.max(2500, (20 / wpm) * 60000 + 800));
    void run("Play sample", () => api.previewPrefs(what));
  };
  const silent = view.speech_backend === "mock" || view.speech_backend === "none";
  const ticks = [lo, NORMAL_WPM, 270, 360].filter((t, i, a) => t >= lo && t <= hi && a.indexOf(t) === i);
  const volPct = Math.round((vol / vhi) * 100);
  const sounds = view.sounds.length ? view.sounds : [view.prefs.received_sound];

  return (
    <div className="audio-settings" data-testid="audio-settings">
      <div className="audio-head">
        <span className="label-caps">Audio · saved for you</span>
        <span className="audio-instant">
          <span className="mono">✓</span> applies instantly
        </span>
      </div>
      <div className="audio-block">
        <div className="audio-line">
          <span className="audio-name" id="speed-l">
            Speech speed
          </span>
          <span className="audio-val mono">
            {wpm} wpm <span className="audio-x">≈ {speedX(wpm)}×</span>
          </span>
        </div>
        <input
          type="range"
          className="audio-range"
          min={lo}
          max={hi}
          step={10}
          value={wpm}
          aria-labelledby="speed-l"
          aria-valuetext={`${wpm} words per minute, about ${speedX(wpm)} times`}
          onChange={(e) => onRate(Number(e.target.value))}
        />
        <div className="audio-ticks mono" aria-hidden="true">
          {ticks.map((t) => (
            <span key={t}>{t === lo ? t : `${speedX(t)}× ${t}`}</span>
          ))}
        </div>
        <button type="button" className={playing === "speech" ? "audio-play is-on" : "audio-play"} onClick={() => void hear("speech")}>
          {playing === "speech" ? `◀ Speaking at ${speedX(wpm)}×` : "▶ Hear the speed"}
        </button>
      </div>
      <div className="audio-block">
        <span className="audio-name" id="sound-l">
          “Photo received” sound
        </span>
        <div className="audio-sounds" role="radiogroup" aria-labelledby="sound-l">
          {sounds.map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={view.prefs.received_sound === s}
              className="audio-sound"
              onClick={() => void save({ received_sound: s })}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="audio-vol">
          <span className="audio-t2" id="vol-l">
            Volume
          </span>
          <input
            type="range"
            className="audio-range"
            min={vlo}
            max={vhi}
            step={0.25}
            value={vol}
            aria-labelledby="vol-l"
            aria-valuetext={`${volPct}%`}
            onChange={(e) => onVol(Number(e.target.value))}
          />
          <span className="mono audio-pct">{volPct}%</span>
        </div>
        <button type="button" className={playing === "mix" ? "audio-play is-on" : "audio-play"} onClick={() => void hear("mix")}>
          {playing === "mix" ? `◀ ${view.prefs.received_sound} over speech` : "▶ Hear it over speech"}
        </button>
        <span className="audio-note">
          The sample plays the sound while a sentence is being spoken, which is how you'll hear it during a shoot.
        </span>
      </div>
      {silent && <p className="pop-note">Speech is {view.speech_backend} here, so samples are silent.</p>}
    </div>
  );
}

/** Top-bar coaching pill: on/paused, paid-call meter, and a popover with the caps. */
export function CoachingPill() {
  const { sid, state, run, refresh, toast } = useApp();
  const [open, setOpen] = useState(false);
  const [usd, setUsd] = useState("");
  const [cue, setCue] = useState<string | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  useDismiss(open, () => setOpen(false), wrap, btn);
  useShortcuts((s) => {
    if (s.kind === "settings") {
      setOpen((o) => !o);
      return true;
    }
    return false;
  });

  const session = state?.session;
  useEffect(() => {
    if (open && session) setUsd(session.budget_usd != null ? session.budget_usd.toFixed(2) : "");
    // Only when the popover opens: don't overwrite what is being typed.
  }, [open]);
  useEffect(() => {
    if (!open || cue) return;
    let alive = true;
    api
      .diagnostics(sid)
      .then((d) => alive && setCue(String(d.config.received_cue ?? "sound")))
      .catch(() => alive && setCue("unknown"));
    return () => {
      alive = false;
    };
  }, [open, cue, sid]);

  if (!sid || !state || !session) return null;
  const u = state.usage;
  const paused = session.coaching_paused;
  const used = u?.capped_calls ?? null;
  const cap = u?.max_model_calls ?? session.max_model_calls;
  const cost = u?.estimated_cost_usd ?? null;
  const pct = cap && used != null ? Math.min(100, Math.round((used / cap) * 100)) : 0;
  const perCall = used && cost != null ? cost / used : null;

  const patch = (label: string, body: Parameters<typeof api.patchSession>[1]) =>
    run(label, async () => {
      await api.patchSession(sid, body);
      await refresh();
    });
  const setPaused = (p: boolean) => {
    if (p === paused) return;
    void patch(p ? "Pause coaching" : "Resume coaching", { coaching_paused: p });
  };
  const stepCap = (dir: -1 | 1) => {
    const base = cap ?? Math.ceil(((used ?? 0) + 10) / 10) * 10;
    const next = cap == null ? base : Math.max(10, base + dir * 10);
    void patch("Update call cap", { max_model_calls: next });
  };
  const commitUsd = () => {
    const t = usd.trim().replace(/^\$/, "");
    const cur = session.budget_usd;
    if (t === "") {
      if (cur != null) void patch("Update spend cap", { budget_usd: null });
      return;
    }
    const v = Number(t);
    if (!Number.isFinite(v) || v < 0) {
      toast({ glyph: "!", text: "Spend cap must be a dollar amount", tone: "unc" });
      return;
    }
    if (v !== cur) void patch("Update spend cap", { budget_usd: Math.round(v * 100) / 100 });
  };

  return (
    <div className="coach-pill-wrap" ref={wrap}>
      <button
        ref={btn}
        type="button"
        className="coach-pill"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-keyshortcuts="P Meta+,"
        onClick={() => setOpen((o) => !o)}
      >
        <span className={paused ? "coach-pill-state is-paused" : "coach-pill-state"} data-testid="coaching-status">
          <span className="glyph" aria-hidden="true">{paused ? "‖" : "●"}</span>
          {paused ? "Paused" : "Coaching on"}
        </span>
        <span className="coach-pill-meter">
          <span className="mono" data-testid="usage">{usageLine(used, cap, cost)}</span>
          <span className={paused ? "meter is-paused" : "meter"} aria-hidden="true">
            <span style={{ width: `${pct}%` }} />
          </span>
        </span>
        <span aria-hidden="true" className="muted" style={{ fontSize: 10 }}>▾</span>
      </button>
      {open && (
        <div className="popover coach-pop" role="dialog" aria-label="Coaching">
          <div className="coach-pop-head">
            <h2>Coaching <span className="mono muted small">⌘,</span></h2>
            <div className="seg" role="group" aria-label="Coaching on or paused">
              <button type="button" aria-pressed={!paused} onClick={() => setPaused(false)}>On</button>
              <button type="button" aria-pressed={paused} onClick={() => setPaused(true)}>Paused</button>
            </div>
          </div>
          {paused && session.paused_reason && <p className="pop-note">Paused: {session.paused_reason}</p>}
          <div className="coach-pop-grid">
            <span>
              Paid-call cap<span className="sub">{used ?? 0} used this session</span>
            </span>
            <div className="stepper">
              <button type="button" aria-label="Lower cap" onClick={() => stepCap(-1)} disabled={cap == null || cap <= 10}>−</button>
              <output aria-label="Paid-call cap">{cap ?? "—"}</output>
              <button type="button" aria-label="Raise cap" onClick={() => stepCap(1)}>+</button>
            </div>
            <span>
              Spend cap (USD)
              <span className="sub">
                {perCall != null ? `≈ $${perCall.toFixed(3)} per call so far` : "Only priced models count"}
                {u?.unpriced_calls ? ` · ${u.unpriced_calls} unpriced` : ""}
              </span>
            </span>
            <label className="usd-input">
              <span className="mono muted" aria-hidden="true">$</span>
              <span className="sr-only">Spend cap in US dollars</span>
              <input
                inputMode="decimal"
                value={usd}
                placeholder="none"
                onChange={(e) => setUsd(e.target.value)}
                onBlur={commitUsd}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitUsd();
                }}
              />
            </label>
          </div>
          <p className="pop-note">
            Coaching pauses at whichever cap is hit first. Photos and local measurements continue.
            {u?.exceeded && <strong className="tone-unc"> Cap reached{u.reason ? `: ${u.reason}` : ""}.</strong>}
            {u?.note && ` ${u.note}`}
          </p>
          <div className="pop-rule" />
          <AudioSettings />
          <div className="field">
            <span className="small">When a photo is received</span>
            <p className="pop-note">
              {cue == null ? "Checking…" : CUE_TEXT[cue] ?? "Not reported by the server."} Change the mode with
              APERTURE_ALLY_RECEIVED_CUE (sound, speech or none) and restart the app.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/** "What I changed for the next shot" — attached to the next photo of the active shot. */
export function ChangeNote() {
  const { sid, state, run, pendingNote: localNote, setPendingNote } = useApp();
  const [text, setText] = useState("");
  if (!sid || !state) return null;
  // The server snapshot is authoritative (survives reloads, includes notes spoken as "I moved…").
  const pendingNote = state.pending_change !== undefined ? state.pending_change : localNote;
  return (
    <section className="panel" aria-labelledby="change-h">
      <h2 id="change-h">What I changed for the next shot</h2>
      <form
        className="inline-form"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await run("Save change note", () => api.changeNote(sid, text.trim() || null));
          if (r) {
            setPendingNote(r.pending_change);
            setText("");
          }
        }}
      >
        <label className="grow">
          <span className="sr-only">What I changed</span>
          <input
            value={text}
            maxLength={500}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. moved the light a hand-width left"
          />
        </label>
        <button type="submit">Save note</button>
      </form>
      <p className="small" role="status">
        {pendingNote ? (
          <>
            Pending for the next photo of {shotTitle(state.shots, state.session.active_shot_id)}: <em>“{pendingNote}”</em>{" "}
            <button
              type="button"
              className="link"
              onClick={() =>
                run("Clear change note", async () => {
                  await api.changeNote(sid, null);
                  setPendingNote(null);
                })
              }
            >
              Clear
            </button>
          </>
        ) : (
          <span className="muted">No pending note.</span>
        )}
      </p>
    </section>
  );
}
