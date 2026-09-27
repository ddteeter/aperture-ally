import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useApp } from "../AppContext";
import { shotTitle } from "../lib/format";

/** "Received ✓ photo #N" — confirms the backend has the file before Drew switches shots. */
export function ReceivedIndicator() {
  const { state, received } = useApp();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (!state) return null;
  // Before any capture.ready event this page load, fall back to the newest capture in the snapshot.
  const newest = state.captures.reduce<(typeof state.captures)[number] | null>((a, c) => (!a || c.seq > a.seq ? c : a), null);
  const pending = state.pending_files.filter((p) => p.status !== "failed");
  const ago = received ? Math.max(0, Math.round((now - received.at) / 1000)) : null;
  return (
    <section className="panel received" aria-labelledby="received-h">
      <h2 id="received-h" className="sr-only">
        Last received photo
      </h2>
      <p role="status" aria-live="polite" className="received-line" data-testid="received">
        {received ? (
          <>
            <strong className="big">Received ✓ photo #{received.seq}</strong>{" "}
            <span className="small">
              for {shotTitle(state.shots, received.shotId)}
              {received.ambiguous && " · shot attribution uncertain — check the filmstrip"}
            </span>
          </>
        ) : newest ? (
          <span>
            Last received: photo #{newest.seq} for {shotTitle(state.shots, newest.shot_id)}. Waiting for the next photo…
          </span>
        ) : (
          <span>Waiting for the first photo…</span>
        )}
      </p>
      {/* kept outside the live region so the ticking counter isn't announced */}
      {ago != null && <p className="small muted">{ago}s ago</p>}
      {pending.length > 0 && (
        <p className="small">
          Still arriving: {pending.map((p) => `${p.name} (${p.status.replace(/_/g, " ")})`).join(", ")}
        </p>
      )}
      <p className="small muted">Wait for “Received ✓” before switching shots.</p>
    </section>
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

/** Auto-coaching on/off and the per-session paid-call / spend caps. */
export function CoachingControl() {
  const { sid, state, run } = useApp();
  const [calls, setCalls] = useState("");
  const [usd, setUsd] = useState("");
  if (!sid || !state) return null;
  const { session } = state;
  const u = state.usage;
  const paused = session.coaching_paused;
  return (
    <section className="panel" aria-labelledby="coaching-h">
      <h2 id="coaching-h">Coaching</h2>
      <p role="status" data-testid="coaching-status">
        <strong>{paused ? "Paused" : "On"}</strong>
        {paused && session.paused_reason ? ` — ${session.paused_reason}` : ""}
        {paused && <span className="small muted"> · photos are still saved; “Review again” still works</span>}
      </p>
      <button
        type="button"
        onClick={() => run(paused ? "Resume coaching" : "Pause coaching", () => api.patchSession(sid, { coaching_paused: !paused }))}
      >
        {paused ? "Resume coaching" : "Pause coaching"}
      </button>
      <p className="small muted">Voice: “pause coaching” / “resume coaching”. A remote key can be set as APERTURE_ALLY_PAUSE_KEY.</p>
      {u && (
        <p className="small" data-testid="usage">
          Paid coaching calls: {u.capped_calls}
          {u.max_model_calls != null ? ` / ${u.max_model_calls}` : ""} · est. spend $
          {u.estimated_cost_usd.toFixed(2)}
          {u.budget_usd != null ? ` / $${u.budget_usd.toFixed(2)}` : ""}
          {u.unpriced_calls > 0 && ` · ${u.unpriced_calls} unpriced`}
          {u.exceeded && <strong> · cap reached</strong>}
          {u.note && <span className="muted"> ({u.note})</span>}
        </p>
      )}
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          const body: { max_model_calls?: number | null; budget_usd?: number | null } = {};
          if (calls.trim() !== "") body.max_model_calls = calls.trim() === "default" ? null : Number(calls);
          if (usd.trim() !== "") body.budget_usd = usd.trim() === "default" ? null : Number(usd);
          if (Object.keys(body).length === 0) return;
          void run("Update caps", async () => {
            await api.patchSession(sid, body);
            setCalls("");
            setUsd("");
          });
        }}
      >
        <label>
          Call cap
          <input inputMode="numeric" value={calls} onChange={(e) => setCalls(e.target.value)} placeholder={String(session.max_model_calls ?? "default")} size={7} />
        </label>
        <label>
          $ cap
          <input inputMode="decimal" value={usd} onChange={(e) => setUsd(e.target.value)} placeholder={String(session.budget_usd ?? "default")} size={7} />
        </label>
        <button type="submit">Set caps</button>
      </form>
    </section>
  );
}
