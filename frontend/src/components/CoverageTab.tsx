import { useState } from "react";
import { api } from "../api/client";
import { useApp } from "../AppContext";
import { humanize } from "../lib/format";
import { Chip } from "./Chip";

export function CoverageTab() {
  const { sid, state, run } = useApp();
  const [exported, setExported] = useState<Record<string, string> | null>(null);
  if (!state || !sid) return null;
  const cov = state.coverage;
  const capName = (id: string | undefined) => {
    const c = state.captures.find((x) => x.id === id);
    return c ? c.jpeg_name ?? c.raw_name ?? c.source_names[0] ?? "" : "";
  };

  return (
    <div className="coverage-tab">
      <section className="panel" aria-labelledby="cov-h">
        <h2 id="cov-h">
          Coverage: {cov.resolved} of {cov.total} shots resolved {cov.complete && "— complete ✓"}
        </h2>
        {cov.unresolved.length > 0 ? (
          <div className="unresolved" role="status">
            <strong>Still needed ({cov.unresolved.length}):</strong>
            <ul>
              {cov.unresolved.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="ok-line">Every shot has an accepted keeper.</p>
        )}
        <p className="small">AI verdicts are advisory; only accepted keepers resolve a shot.</p>
        <div className="table-wrap">
          <table data-testid="coverage-table">
            <thead>
              <tr>
                <th scope="col">Shot</th>
                <th scope="col">State</th>
                <th scope="col">Keeper</th>
                <th scope="col">Photos</th>
                <th scope="col">Latest AI verdict</th>
              </tr>
            </thead>
            <tbody>
              {cov.shots.map((s) => (
                <tr key={s.shot_id} data-testid={`coverage-row-${s.title}`}>
                  <th scope="row">
                    {s.title}
                    <div className="small muted">{s.purpose}</div>
                  </th>
                  <td>
                    <Chip value={s.state} />
                    {s.keeper_problem && <div className="error-text small">{s.keeper_problem}</div>}
                  </td>
                  <td>
                    {s.keeper ? (
                      <>
                        #{s.keeper.capture_seq ?? "?"} <span className="small">{capName(s.keeper.capture_id)}</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{s.captures}</td>
                  <td>
                    {s.latest_ai_verdict ? humanize(s.latest_ai_verdict) : "—"}
                    {s.latest_assessed_seq != null && <span className="small muted"> (#{s.latest_assessed_seq})</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel" aria-labelledby="export-h">
        <h2 id="export-h">Export</h2>
        <button
          type="button"
          className="primary"
          onClick={async () => {
            const r = await run("Export", () => api.exports(sid));
            if (r) setExported(r);
          }}
        >
          Export coverage + timing
        </button>
        {exported && (
          <div role="status">
            <p>Written files:</p>
            <ul className="paths">
              {Object.entries(exported).map(([k, v]) => (
                <li key={k}>
                  <strong>{k}</strong>: <code>{String(v)}</code>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}
