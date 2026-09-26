import { useState } from "react";
import { api } from "../api/client";
import type { Criterion, Shot } from "../api/types";
import { useApp } from "../AppContext";
import { nextCriterionId } from "../lib/regions";
import { splitList } from "../lib/format";
import { Chip } from "./Chip";

export function ShotList() {
  const { state, sid, run, refresh } = useApp();
  if (!state || !sid) return null;
  const activeId = state.session.active_shot_id;
  const cov = new Map(state.coverage.shots.map((c) => [c.shot_id, c]));

  const setActive = (shotId: string) =>
    run("Set active shot", async () => {
      await api.setActiveShot(sid, shotId);
      await refresh();
    });

  const nextUnresolved = () => {
    const order = state.coverage.shots.map((c) => c.shot_id);
    const start = activeId && order.includes(activeId) ? order.indexOf(activeId) + 1 : 0;
    const rotated = [...order.slice(start), ...order.slice(0, start)];
    const next = rotated.find((id) => !cov.get(id)?.resolved && id !== activeId) ?? rotated.find((id) => !cov.get(id)?.resolved);
    if (next) void setActive(next);
  };
  const anyUnresolved = state.coverage.shots.some((c) => !c.resolved);

  return (
    <section className="panel" aria-labelledby="shots-h">
      <h2 id="shots-h">Shots</h2>
      <fieldset className="shot-list">
        <legend className="sr-only">Active shot</legend>
        {state.shots.map((shot) => {
          const c = cov.get(shot.id);
          const active = shot.id === activeId;
          return (
            <div key={shot.id} className={active ? "shot shot-active" : "shot"} data-testid={`shot-${shot.ordinal}`}>
              <label className="shot-radio">
                <input
                  type="radio"
                  name="active-shot"
                  checked={active}
                  onChange={() => void setActive(shot.id)}
                />
                <span className="shot-title">{shot.title}</span>
                {active && <span className="badge badge-active">ACTIVE</span>}
              </label>
              <div className="shot-meta">
                <Chip value={c?.state ?? "missing"} />
                {c?.keeper ? (
                  <span className="small">keeper #{c.keeper.capture_seq ?? "?"}</span>
                ) : null}
                <span className="small muted">{c?.captures ?? 0} photo(s)</span>
                {shot.needs_retake && <span className="badge badge-warn">needs retake (marked)</span>}
              </div>
              <details className="shot-edit">
                <summary>Edit shot</summary>
                <ShotEditor key={shot.id + shot.updated_at} shot={shot} />
              </details>
            </div>
          );
        })}
      </fieldset>
      <button type="button" className="wide" onClick={nextUnresolved} disabled={!anyUnresolved}>
        Next unresolved shot
      </button>
      {!anyUnresolved && <p className="small">All shots have accepted keepers.</p>}
    </section>
  );
}

export function ShotEditor({ shot }: { shot: Shot }) {
  const { sid, run, refresh } = useApp();
  const [title, setTitle] = useState(shot.title);
  const [purpose, setPurpose] = useState(shot.purpose);
  const [mustShow, setMustShow] = useState(shot.must_show.join(", "));
  const [framing, setFraming] = useState(shot.framing);
  const [criteria, setCriteria] = useState<Criterion[]>(shot.criteria);
  const [needsRetake, setNeedsRetake] = useState(shot.needs_retake);
  const [saved, setSaved] = useState<string | null>(null);
  const base = `shot-${shot.id}`;

  const save = async () => {
    if (!sid) return;
    const r = await run("Save shot", () =>
      api.patchShot(sid, shot.id, {
        title: title.trim() || shot.title,
        purpose,
        must_show: splitList(mustShow),
        framing,
        criteria: criteria.filter((c) => c.text.trim()).map((c) => ({ id: c.id, text: c.text.trim() })),
        needs_retake: needsRetake,
      }),
    );
    if (r) {
      setSaved("Saved.");
      await refresh();
    }
  };

  return (
    <form
      className="form-grid compact"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <label>
        Title
        <input value={title} onChange={(e) => setTitle(e.target.value)} required />
      </label>
      <label>
        Purpose
        <textarea rows={2} value={purpose} onChange={(e) => setPurpose(e.target.value)} />
      </label>
      <label>
        Must show (comma separated)
        <input value={mustShow} onChange={(e) => setMustShow(e.target.value)} />
      </label>
      <label>
        Framing
        <textarea rows={2} value={framing} onChange={(e) => setFraming(e.target.value)} />
      </label>
      <fieldset>
        <legend>Criteria</legend>
        {criteria.map((c, i) => (
          <div key={c.id} className="criterion-row">
            <label htmlFor={`${base}-${c.id}`} className="crit-id">
              {c.id}
            </label>
            <input
              id={`${base}-${c.id}`}
              value={c.text}
              onChange={(e) => setCriteria(criteria.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))}
            />
            <button
              type="button"
              aria-label={`Remove criterion ${c.id}`}
              onClick={() => setCriteria(criteria.filter((_, j) => j !== i))}
            >
              Remove
            </button>
          </div>
        ))}
        <button type="button" onClick={() => setCriteria([...criteria, { id: nextCriterionId(criteria), text: "" }])}>
          Add criterion
        </button>
      </fieldset>
      <label className="check">
        <input type="checkbox" checked={needsRetake} onChange={(e) => setNeedsRetake(e.target.checked)} />
        Needs retake (my judgement)
      </label>
      <p className="small muted">Sharp regions are drawn on the photo in the viewer.</p>
      <div>
        <button type="submit" className="primary">
          Save shot
        </button>{" "}
        {saved && <span role="status">{saved}</span>}
      </div>
    </form>
  );
}
