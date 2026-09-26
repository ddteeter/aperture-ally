import { useState } from "react";
import { api, imageUrl } from "../api/client";
import type { Capture } from "../api/types";
import { useApp } from "../AppContext";
import { humanize, isAnalysing, shotTitle } from "../lib/format";

export function Filmstrip({ selectedId, onSelect }: { selectedId: string | null; onSelect: (id: string) => void }) {
  const { state } = useApp();
  const [onlyActive, setOnlyActive] = useState(false);
  if (!state) return null;
  const active = state.session.active_shot_id;
  const caps = [...state.captures]
    .filter((c) => !onlyActive || c.shot_id === active || c.extra_shot_ids.includes(active ?? ""))
    .sort((a, b) => b.seq - a.seq);

  return (
    <section className="panel filmstrip" aria-labelledby="film-h">
      <div className="viewer-head">
        <h2 id="film-h">Filmstrip ({caps.length})</h2>
        <label className="check">
          <input type="checkbox" checked={onlyActive} onChange={(e) => setOnlyActive(e.target.checked)} />
          Only active shot
        </label>
      </div>
      {state.pending_files.length > 0 && (
        <ul className="pending-files small" aria-label="Files still arriving">
          {state.pending_files.map((p) => (
            <li key={p.name + p.status}>
              {p.name}: <strong>{humanize(p.status)}</strong>
              {p.note ? ` — ${p.note}` : ""}
            </li>
          ))}
        </ul>
      )}
      {caps.length === 0 ? (
        <p className="small muted">No photos yet.</p>
      ) : (
        <ol className="film" reversed>
          {caps.map((c) => (
            <FilmItem key={c.id} c={c} selected={c.id === selectedId} onSelect={() => onSelect(c.id)} />
          ))}
        </ol>
      )}
    </section>
  );
}

function FilmItem({ c, selected, onSelect }: { c: Capture; selected: boolean; onSelect: () => void }) {
  const { state, run, refresh } = useApp();
  const [thumbFailed, setThumbFailed] = useState(false);
  const [reassign, setReassign] = useState(c.shot_id ?? "");
  if (!state) return null;
  const la = c.latest_assessment;
  const aiFailed = la?.status === "failed";
  const ingestFailed = c.processing_state === "failed" && !aiFailed;
  return (
    <li className={selected ? "film-item selected" : "film-item"} data-testid={`film-${c.seq}`}>
      <button
        type="button"
        className="film-btn"
        aria-pressed={selected}
        aria-label={`Show photo #${c.seq}, ${shotTitle(state.shots, c.shot_id)}`}
        onClick={onSelect}
      >
        {thumbFailed || !c.evidence.available ? (
          <span className="thumb-missing">#{c.seq}</span>
        ) : (
          <img
            src={imageUrl(c.id, "thumb") + `?v=${c.evidence.available ? 1 : 0}`}
            alt=""
            loading="lazy"
            onError={() => setThumbFailed(true)}
          />
        )}
      </button>
      <div className="film-badges small">
        <strong>#{c.seq}</strong> {shotTitle(state.shots, c.shot_id)}
        <br />
        <span className="badge">{isAnalysing(c) ? "analysing…" : humanize(c.processing_state)}</span>
        {la?.result && <span className="badge">AI: {humanize(la.result.verdict)}</span>}
        {c.raw_name && <span className="badge">RAW paired</span>}
        {c.recovered && <span className="badge badge-warn">recovered</span>}
        {aiFailed && <span className="badge badge-error">AI failed</span>}
        {ingestFailed && <span className="badge badge-error">failed: {c.error}</span>}
        {c.attribution_ambiguous && <span className="badge badge-warn">shot uncertain</span>}
        {state.keepers.some((k) => k.capture_id === c.id) && <span className="badge badge-ok">keeper ✓</span>}
      </div>
      {c.attribution_ambiguous && (
        <form
          className="reassign small"
          onSubmit={(e) => {
            e.preventDefault();
            void run("Reassign shot", async () => {
              await api.patchCapture(c.id, { shot_id: reassign || null });
              await refresh();
            });
          }}
        >
          <label>
            Reassign shot
            <select value={reassign} onChange={(e) => setReassign(e.target.value)}>
              {state.shots.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title}
                </option>
              ))}
            </select>
          </label>
          <button type="submit">{reassign === c.shot_id ? "Confirm" : "Reassign"}</button>
        </form>
      )}
    </li>
  );
}
