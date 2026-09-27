import { useState, type KeyboardEvent } from "react";
import { api } from "../api/client";
import type { Criterion, Shot, ShotPatch } from "../api/types";
import { useApp } from "../AppContext";
import { nextCriterionId } from "../lib/regions";
import "./workflows.css";
import { reorderPatches, sortedShots } from "./workflowsLogic";

export function ShotListTab() {
  const { sid, state, run, refresh } = useApp();
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!state || !sid) return null;
  const shots = sortedShots(state.shots);
  const sel = shots.find((s) => s.id === selected) ?? shots.find((s) => s.id === state.session.active_shot_id) ?? shots[0] ?? null;

  const move = async (id: string, dir: -1 | 1) => {
    const patches = reorderPatches(state.shots, id, dir);
    if (!patches.length || busy) return;
    setBusy(true);
    await run("Reorder shots", async () => {
      for (const p of patches) await api.patchShot(sid, p.id, { ordinal: p.ordinal });
    });
    await refresh();
    setBusy(false);
  };

  const add = async (body: ShotPatch & { title: string }) => {
    const s = await run("Add shot", () => api.addShot(sid, body));
    if (s) {
      await refresh();
      setSelected(s.id);
    }
  };

  const onRowKey = (e: KeyboardEvent, id: string) => {
    if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault();
    void move(id, e.key === "ArrowUp" ? -1 : 1);
  };

  return (
    <div className="wf-screen wf-split wf-split-rail-420">
      <nav className="wf-rail" aria-labelledby="shotlist-h">
        <div className="wf-rail-head">
          <h2 className="wf-title" id="shotlist-h">
            Shot list
          </h2>
          <span className="wf-t3 wf-xs">↑ ↓ or ⌥↑ ⌥↓ to reorder</span>
        </div>
        <ol className="wf-stack-2">
          {shots.map((s, i) => (
            <li key={s.id} className={s.id === sel?.id ? "wf-shot-row is-sel" : "wf-shot-row"}>
              <button
                type="button"
                className="wf-shot-pick"
                aria-current={s.id === sel?.id ? "true" : undefined}
                onClick={() => setSelected(s.id)}
                onKeyDown={(e) => onRowKey(e, s.id)}
              >
                <span className="wf-mono wf-t3 wf-xs wf-num">{i + 1}</span>
                <span className="wf-stack-2 wf-minw0">
                  <span className="wf-strong">{s.title}</span>
                  <span className="wf-t3 wf-xs">
                    {s.criteria.length} {s.criteria.length === 1 ? "criterion" : "criteria"}
                  </span>
                </span>
              </button>
              <button
                type="button"
                className="wf-icon-btn"
                aria-label={`Move ${s.title} up`}
                disabled={busy || i === 0}
                onClick={() => void move(s.id, -1)}
              >
                ↑
              </button>
              <button
                type="button"
                className="wf-icon-btn"
                aria-label={`Move ${s.title} down`}
                disabled={busy || i === shots.length - 1}
                onClick={() => void move(s.id, 1)}
              >
                ↓
              </button>
            </li>
          ))}
        </ol>
        <button type="button" className="wf-btn-dashed" onClick={() => void add({ title: `Shot ${shots.length + 1}` })}>
          + Add shot
        </button>
      </nav>

      <div className="wf-main wf-main-narrow">
        {sel ? (
          <ShotForm
            key={sel.id + sel.updated_at}
            shot={sel}
            onDuplicate={(d) =>
              void add({
                title: `${d.title} (copy)`,
                purpose: d.purpose,
                must_show: d.must_show,
                framing: d.framing,
                criteria: d.criteria,
              })
            }
          />
        ) : (
          <p className="wf-t2">No shots yet. Add one to start.</p>
        )}
      </div>
    </div>
  );
}

type Draft = Pick<Shot, "title" | "purpose" | "must_show" | "framing" | "criteria" | "needs_retake">;

export function ShotForm({ shot, onDuplicate }: { shot: Shot; onDuplicate?: (d: Draft) => void }) {
  const { sid, run, refresh } = useApp();
  const [title, setTitle] = useState(shot.title);
  const [purpose, setPurpose] = useState(shot.purpose);
  const [mustShow, setMustShow] = useState<string[]>(shot.must_show);
  const [newMust, setNewMust] = useState("");
  const [framing, setFraming] = useState(shot.framing);
  const [criteria, setCriteria] = useState<Criterion[]>(shot.criteria);
  const [needsRetake, setNeedsRetake] = useState(shot.needs_retake);
  const [saved, setSaved] = useState<string | null>(null);
  const base = `shot-${shot.id}`;

  const draft = (): Draft => ({
    title: title.trim() || shot.title,
    purpose,
    must_show: mustShow,
    framing,
    criteria: criteria.filter((c) => c.text.trim()).map((c) => ({ id: c.id, text: c.text.trim() })),
    needs_retake: needsRetake,
  });

  const addMust = () => {
    const v = newMust.trim();
    if (v && !mustShow.includes(v)) setMustShow([...mustShow, v]);
    setNewMust("");
  };

  const save = async () => {
    if (!sid) return;
    const r = await run("Save shot", () => api.patchShot(sid, shot.id, draft()));
    if (r) {
      setSaved("Saved.");
      await refresh();
    }
  };

  return (
    <form
      className="wf-stack-20"
      aria-label={`Edit shot: ${shot.title}`}
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <label className="wf-field">
        <span className="wf-label">Shot name</span>
        <input className="wf-input wf-input-xl" value={title} onChange={(e) => setTitle(e.target.value)} required />
      </label>
      <label className="wf-field">
        <span className="wf-label">Purpose — why this shot exists for the reader</span>
        <textarea className="wf-input wf-textarea" rows={3} value={purpose} onChange={(e) => setPurpose(e.target.value)} />
      </label>

      <fieldset className="wf-fieldset">
        <legend className="wf-label">Must show</legend>
        <div className="wf-chips">
          {mustShow.map((m) => (
            <span key={m} className="wf-chip">
              {m}
              <button
                type="button"
                className="wf-chip-x"
                aria-label={`Remove ${m}`}
                onClick={() => setMustShow(mustShow.filter((x) => x !== m))}
              >
                ×
              </button>
            </span>
          ))}
          <span className="wf-chip wf-chip-add">
            <label htmlFor={`${base}-must`} className="sr-only">
              Add a must-show item
            </label>
            <input
              id={`${base}-must`}
              className="wf-chip-input"
              placeholder="+ Add"
              value={newMust}
              onChange={(e) => setNewMust(e.target.value)}
              onBlur={addMust}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  addMust();
                }
              }}
            />
          </span>
        </div>
      </fieldset>

      <label className="wf-field">
        <span className="wf-label">Framing</span>
        <textarea className="wf-input wf-textarea" rows={2} value={framing} onChange={(e) => setFraming(e.target.value)} />
      </label>

      <fieldset className="wf-fieldset">
        <legend className="wf-label wf-legend-row">
          Acceptance criteria
          <span className="wf-t3 wf-xs">Free text · 2–3 work best · the coach checks each one</span>
        </legend>
        {criteria.map((c, i) => (
          <div key={c.id} className="wf-crit-row">
            <label htmlFor={`${base}-${c.id}`} className="wf-mono wf-t3 wf-num">
              {i + 1}
              <span className="sr-only"> Criterion {i + 1}</span>
            </label>
            <input
              id={`${base}-${c.id}`}
              className="wf-input"
              value={c.text}
              onChange={(e) => setCriteria(criteria.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))}
            />
            <button
              type="button"
              className="wf-icon-btn"
              aria-label={`Remove criterion ${i + 1}`}
              onClick={() => setCriteria(criteria.filter((_, j) => j !== i))}
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          className="wf-btn-dashed wf-self-start"
          onClick={() => setCriteria([...criteria, { id: nextCriterionId(criteria), text: "" }])}
        >
          + Add criterion
        </button>
      </fieldset>

      <label className="wf-check">
        <input type="checkbox" checked={needsRetake} onChange={(e) => setNeedsRetake(e.target.checked)} />
        <span>Needs retake (my judgement)</span>
      </label>
      <p className="wf-t3 wf-xs">Sharp regions are drawn on the photo in the Shoot tab.</p>

      <div className="wf-row-8">
        <button type="submit" className="wf-btn wf-btn-pri">
          Save shot
        </button>
        {onDuplicate && (
          <button type="button" className="wf-btn" onClick={() => onDuplicate(draft())}>
            Duplicate
          </button>
        )}
        {saved && (
          <span role="status" className="wf-ok wf-small wf-center">
            ✓ {saved}
          </span>
        )}
      </div>
    </form>
  );
}
