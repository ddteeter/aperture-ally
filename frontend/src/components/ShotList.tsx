import { type KeyboardEvent as RKeyboardEvent, useRef, useState } from "react";
import { api } from "../api/client";
import type { Criterion, Shot } from "../api/types";
import { useApp } from "../AppContext";
import { isAnalysing, splitList } from "../lib/format";
import { nextCriterionId } from "../lib/regions";
import { CAPTURE_STATE, shotStateMeta, type StatusMeta } from "../ui/status";
import { ShootOriginBar, TodayNotes, shotMarks } from "./ShootTemplate";

/** Shot rail: the shot list with glyph statuses and the coverage meter. Collapses to a 56 px rail with `[`. */
export function ShotList({ collapsed = false, onToggleCollapsed }: { collapsed?: boolean; onToggleCollapsed?: () => void }) {
  const { state, sid, run, refresh } = useApp();
  // Optimistic selection so the row responds immediately; the snapshot stays authoritative.
  const [pendingActive, setPendingActive] = useState<string | null>(null);
  const rows = useRef<(HTMLButtonElement | null)[]>([]);
  if (!state || !sid) return null;
  const activeId = pendingActive ?? state.session.active_shot_id;
  const marks = shotMarks(state.origin?.changes ?? []);
  const cov = new Map(state.coverage.shots.map((c) => [c.shot_id, c]));
  const keepers = state.coverage.shots.filter((c) => c.state === "accepted").length;
  const total = state.shots.length;

  const setActive = async (shotId: string) => {
    if (shotId === activeId) return;
    setPendingActive(shotId);
    await run("Set active shot", async () => {
      await api.setActiveShot(sid, shotId);
      await refresh();
    });
    setPendingActive(null);
  };

  const statusOf = (shot: Shot): StatusMeta => {
    const analysing = state.captures.some((c) => c.shot_id === shot.id && isAnalysing(c));
    return analysing ? CAPTURE_STATE.analysing : shotStateMeta(cov.get(shot.id)?.state ?? "missing");
  };

  const nextUnresolved = () => {
    const order = state.coverage.shots.map((c) => c.shot_id);
    const start = activeId && order.includes(activeId) ? order.indexOf(activeId) + 1 : 0;
    const rotated = [...order.slice(start), ...order.slice(0, start)];
    const next = rotated.find((id) => !cov.get(id)?.resolved && id !== activeId) ?? rotated.find((id) => !cov.get(id)?.resolved);
    if (next) void setActive(next);
  };
  const anyUnresolved = state.coverage.shots.some((c) => !c.resolved);

  const onRowKey = (e: RKeyboardEvent, i: number) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const j = (i + (e.key === "ArrowDown" ? 1 : -1) + state.shots.length) % state.shots.length;
    rows.current[j]?.focus();
    void setActive(state.shots[j].id);
  };

  return (
    <aside className={collapsed ? "shot-rail is-collapsed" : "shot-rail"} aria-labelledby="shots-h">
      <div className="rail-head">
        <h2 id="shots-h" className={collapsed ? "sr-only" : "label-caps"}>
          Shot list
        </h2>
        {!collapsed && (
          <a className="rail-edit" href="#shotlist">
            Edit
          </a>
        )}
        <button
          type="button"
          className="rail-toggle"
          aria-label={collapsed ? "Expand shot list" : "Collapse shot list"}
          aria-expanded={!collapsed}
          aria-keyshortcuts="["
          title={collapsed ? "Expand shot list ([)" : "Collapse shot list ([)"}
          onClick={onToggleCollapsed}
        >
          <span aria-hidden="true">{collapsed ? "»" : "«"}</span>
        </button>
      </div>
      {!collapsed && (
        <div className="rail-origin">
          <ShootOriginBar compact />
        </div>
      )}
      <div className="rail-list" role="radiogroup" aria-labelledby="shots-h">
        {state.shots.map((shot, i) => {
          const st = statusOf(shot);
          const active = shot.id === activeId;
          const n = i + 1;
          return (
            <button
              key={shot.id}
              ref={(el) => {
                rows.current[i] = el;
              }}
              type="button"
              role="radio"
              aria-checked={active}
              tabIndex={active || (!activeId && i === 0) ? 0 : -1}
              className={active ? "rail-row is-active" : "rail-row"}
              data-testid={`shot-${shot.ordinal}`}
              title={collapsed ? `${n} ${shot.title} · ${st.word}` : undefined}
              onClick={() => void setActive(shot.id)}
              onKeyDown={(e) => onRowKey(e, i)}
            >
              <span className="rail-line">
                <span className="rail-n mono" aria-hidden="true">{n}</span>
                <span className={collapsed ? "sr-only" : "rail-title"}>
                  {shot.title}
                  {!collapsed && marks.get(n) && <span className="st-mark rail-mark">{marks.get(n)}</span>}
                </span>
                <span className="rail-glyph glyph" style={{ color: st.color }} aria-hidden="true">
                  {st.glyph}
                </span>
                <span className="sr-only">, {st.word}</span>
              </span>
              {active && !collapsed && (
                <span className="rail-detail">
                  {shot.purpose && <span className="rail-purpose">{shot.purpose}</span>}
                  <span className="rail-chip" style={{ color: st.color }}>
                    <span className="glyph" aria-hidden="true">{st.glyph}</span>
                    {st.word}
                    {cov.get(shot.id)?.keeper?.capture_seq != null && ` · #${cov.get(shot.id)!.keeper!.capture_seq}`}
                  </span>
                </span>
              )}
            </button>
          );
        })}
        {state.shots.length === 0 && !collapsed && (
          <p className="rail-empty small muted">
            No shots yet. <a href="#shotlist">Add shots</a>
          </p>
        )}
      </div>
      {!collapsed && anyUnresolved && (
        <button type="button" className="btn-text rail-next" onClick={nextUnresolved}>
          Next unresolved shot →
        </button>
      )}
      {!collapsed && <TodayNotes />}
      <a className="rail-coverage" href="#coverage" aria-label={`Coverage: ${keepers} of ${total} keepers`}>
        {collapsed ? (
          <span className="mono small">
            {keepers}/{total}
          </span>
        ) : (
          <span className="rail-coverage-line">
            <span>Coverage</span>
            <span className="muted">
              {keepers} / {total} keepers
            </span>
          </span>
        )}
        <span className="rail-meter" aria-hidden="true">
          <span style={{ width: `${total ? Math.round((keepers / total) * 100) : 0}%` }} />
        </span>
      </a>
    </aside>
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
