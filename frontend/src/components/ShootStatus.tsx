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
              for {shotTitle(state.shots, received.shotId)} · {ago}s ago
              {received.ambiguous && " · shot attribution uncertain — check the filmstrip"}
            </span>
          </>
        ) : (
          <span>Waiting for the next photo…</span>
        )}
      </p>
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
  const { sid, state, run, pendingNote, setPendingNote } = useApp();
  const [text, setText] = useState("");
  if (!sid || !state) return null;
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
