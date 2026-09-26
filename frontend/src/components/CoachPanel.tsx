import { useState } from "react";
import { api } from "../api/client";
import type { Assessment, Capture, Experiment, Keeper, Shot } from "../api/types";
import { useApp } from "../AppContext";
import { humanize, isAnalysing, ms } from "../lib/format";
import { Chip } from "./Chip";

export interface CoachPanelProps {
  capture: Capture | null;
  shot: Shot | null;
  captures: Capture[];
  experiments: Experiment[];
  keeper: Keeper | null;
}

export function CoachPanel({ capture, shot, captures, experiments, keeper }: CoachPanelProps) {
  const { run, refresh } = useApp();
  const la = capture?.latest_assessment ?? null;
  const analysing = capture ? isAnalysing(capture) : false;
  const seq = (id: string | null | undefined) => captures.find((c) => c.id === id)?.seq ?? "?";
  const related = capture
    ? experiments.filter((e) => e.baseline_capture_id === capture.id || e.follow_up_capture_id === capture.id)
    : [];

  const reviewAgain = () =>
    capture &&
    run("Review again", async () => {
      await api.assess(capture.id, {});
      await refresh();
    });

  return (
    <section className="panel coach" aria-labelledby="coach-h" data-testid="coach-panel">
      <h2 id="coach-h">Coach{capture ? ` — photo #${capture.seq}` : ""}</h2>

      {/* Always-present live region so new advice is announced. */}
      <div aria-live="polite" aria-atomic="true" className="spoken" data-testid="coach-spoken">
        {analysing ? (
          <p className="analysing">
            <span className="spinner" aria-hidden="true" /> Analysing…
          </p>
        ) : la?.status === "completed" && la.result ? (
          <p className="spoken-text">{la.result.spoken_text}</p>
        ) : null}
      </div>

      {!capture && <p>Select a photo to see coaching.</p>}
      {capture && !la && !analysing && (
        <p className="muted">
          {capture.processing_state === "failed"
            ? `This photo could not be processed: ${capture.error ?? "unknown error"}`
            : "Not analysed yet."}
        </p>
      )}

      {la?.status === "failed" && !analysing && (
        <div className="coach-failed" role="alert">
          <p>
            <strong>Analysis failed:</strong> {la.error ?? "unknown error"}
          </p>
          {la.error?.startsWith("AI unavailable") && (
            <p>The AI is unavailable right now. Local features — measurements, crops, before/after, keepers and coverage — still work.</p>
          )}
          <button
            type="button"
            className="primary"
            onClick={() =>
              capture &&
              run("Retry analysis", async () => {
                await api.assess(capture.id, {});
                await refresh();
              })
            }
          >
            Retry
          </button>
        </div>
      )}

      {la?.status === "completed" && la.result && !analysing && (
        <AssessmentView a={la} shot={shot} seqOf={seq} />
      )}

      {capture && (
        <div className="button-row">
          <button type="button" onClick={() => void reviewAgain()} disabled={analysing}>
            Review again
          </button>
          <button type="button" onClick={() => void run("Repeat advice", () => api.coachRepeat())}>
            Repeat last advice
          </button>
          <button type="button" onClick={() => void run("Stop speech", () => api.coachStop())}>
            Stop speech
          </button>
        </div>
      )}

      {related.map((e) => (
        <ExperimentCard key={e.id + e.updated_at} e={e} seqOf={seq} />
      ))}

      {capture && <KeeperControl capture={capture} shot={shot} keeper={keeper} seqOf={seq} />}
    </section>
  );
}

export function AssessmentView({
  a,
  shot,
  seqOf,
}: {
  a: Assessment;
  shot: Shot | null;
  seqOf: (id: string | null | undefined) => number | string;
}) {
  const r = a.result!;
  const pa = r.primary_action;
  const critText = (id: string) => shot?.criteria.find((c) => c.id === id)?.text ?? "(criterion no longer on shot)";
  const tokens = a.usage ? `${a.usage.input_tokens ?? 0} in / ${a.usage.output_tokens ?? 0} out tokens` : "tokens n/a";
  return (
    <div className="assessment">
      <p className="verdict-line">
        <Chip value={r.verdict} label="AI verdict" /> <span className="small muted">(advisory — only you accept keepers)</span>
      </p>

      {r.comparison && (
        <div className="comparison" data-testid="comparison">
          <h3>
            Comparison vs #{seqOf(r.comparison.baseline_capture_id)}: <Chip value={r.comparison.outcome} kind={`cmp-${r.comparison.outcome}`} />
          </h3>
          <p>{r.comparison.evidence}</p>
        </div>
      )}

      {pa && (
        <div className="primary-action">
          <h3>Next change</h3>
          <p className="instruction">
            <strong>{pa.instruction}</strong>
          </p>
          <dl className="kv">
            <dt>Why</dt>
            <dd>{pa.explanation}</dd>
            <dt>Expected effect</dt>
            <dd>{pa.expected_effect}</dd>
            {pa.tradeoff && (
              <>
                <dt>Trade-off</dt>
                <dd>{pa.tradeoff}</dd>
              </>
            )}
            {pa.hold_constant && (
              <>
                <dt>Keep the same</dt>
                <dd>{pa.hold_constant}</dd>
              </>
            )}
            {pa.prerequisites.length > 0 && (
              <>
                <dt>Only if</dt>
                <dd>{pa.prerequisites.join("; ")}</dd>
              </>
            )}
          </dl>
        </div>
      )}

      {a.exposure_note && (
        <div className="exposure-note">
          <h3>Exposure</h3>
          {a.exposure_note.applicable ? (
            <p>{a.exposure_note.note}</p>
          ) : (
            <>
              <p>Exposure equivalence not applied:</p>
              <ul>
                {a.exposure_note.reasons.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {r.criterion_results.length > 0 && (
        <div className="table-wrap">
          <table className="compact-table">
            <caption>Criteria</caption>
            <thead>
              <tr>
                <th scope="col">Criterion</th>
                <th scope="col">Result</th>
                <th scope="col">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {r.criterion_results.map((cr) => (
                <tr key={cr.criterion_id}>
                  <th scope="row">
                    {cr.criterion_id}: {critText(cr.criterion_id)}
                  </th>
                  <td>
                    <Chip value={cr.result} kind={`res-${cr.result}`} />
                  </td>
                  <td>{cr.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {r.observations.length > 0 && (
        <div>
          <h3>Observations</h3>
          <ul className="observations">
            {r.observations.map((o, i) => (
              <li key={i}>
                <span className="badge">{o.severity}</span> {o.observation}{" "}
                <span className="small muted">
                  ({o.region_id ? `region ${o.region_id}, ` : ""}from {humanize(o.evidence_source)})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {r.alternative_causes.length > 0 && (
        <p>
          <strong>Could also be:</strong> {r.alternative_causes.join("; ")}
        </p>
      )}
      {r.question_for_user && (
        <p className="question">
          <strong>Coach asks:</strong> {r.question_for_user}
        </p>
      )}
      {r.teaching_prompt && (
        <p className="teaching">
          <strong>Think about it:</strong> {r.teaching_prompt}
        </p>
      )}
      {a.warnings.length > 0 && (
        <ul className="warnings">
          {a.warnings.map((w, i) => (
            <li key={i}>Warning: {w}</li>
          ))}
        </ul>
      )}

      <p className="meta small muted" data-testid="coach-meta">
        {a.provider} · {a.model_resolved ?? a.model_requested ?? "model n/a"} · prompt {a.prompt_version} ·{" "}
        {ms(a.timings?.total_ms)} · {tokens} ·{" "}
        {a.cost_estimate_usd != null ? `~$${a.cost_estimate_usd.toFixed(4)}` : "cost n/a"} · speech{" "}
        {humanize(a.speech_status)} · {a.kind} ({a.trigger})
        {a.repair_attempted ? " · output repaired once" : ""}
      </p>
    </div>
  );
}

type Tri = "yes" | "no" | "unknown";
const toTri = (b: boolean | null): Tri => (b === true ? "yes" : b === false ? "no" : "unknown");
const fromTri = (t: Tri): boolean | null => (t === "yes" ? true : t === "no" ? false : null);

export function ExperimentCard({ e, seqOf }: { e: Experiment; seqOf: (id: string | null | undefined) => number | string }) {
  const { run, refresh } = useApp();
  const [actual, setActual] = useState(e.actual_change ?? "");
  const [rating, setRating] = useState<string>(e.user_rating ?? "");
  const [improved, setImproved] = useState<Tri>(toTri(e.criterion_improved));
  const [worsened, setWorsened] = useState<Tri>(toTri(e.other_criteria_worsened));
  const [lesson, setLesson] = useState(e.lesson ?? "");
  const [saved, setSaved] = useState(false);
  const id = `exp-${e.id}`;
  return (
    <details className="experiment" open>
      <summary>
        <h3 className="inline-h">
          Experiment: #{seqOf(e.baseline_capture_id)} → {e.follow_up_capture_id ? `#${seqOf(e.follow_up_capture_id)}` : "next photo"}
        </h3>
      </summary>
      <dl className="kv">
        <dt>Suggested</dt>
        <dd>{e.suggested_adjustment}</dd>
        {e.held_constant && (
          <>
            <dt>Held constant</dt>
            <dd>{e.held_constant}</dd>
          </>
        )}
        {e.intended_effect && (
          <>
            <dt>Intended effect</dt>
            <dd>{e.intended_effect}</dd>
          </>
        )}
        <dt>AI comparison</dt>
        <dd>{e.comparison_outcome ? <Chip value={e.comparison_outcome} kind={`cmp-${e.comparison_outcome}`} /> : "not compared yet"}</dd>
      </dl>
      <form
        className="form-grid compact"
        onSubmit={async (ev) => {
          ev.preventDefault();
          const r = await run("Save experiment", () =>
            api.patchExperiment(e.id, {
              actual_change: actual.trim() || null,
              user_rating: (rating || null) as Experiment["user_rating"],
              criterion_improved: fromTri(improved),
              other_criteria_worsened: fromTri(worsened),
              lesson: lesson.trim() || null,
            }),
          );
          if (r) {
            setSaved(true);
            await refresh();
          }
        }}
      >
        <label>
          What I actually changed
          <input value={actual} onChange={(x) => setActual(x.target.value)} />
        </label>
        <label>
          Was the advice…
          <select value={rating} onChange={(x) => setRating(x.target.value)}>
            <option value="">not rated</option>
            <option value="helpful">helpful</option>
            <option value="neutral">neutral</option>
            <option value="harmful">harmful</option>
          </select>
        </label>
        <label htmlFor={`${id}-imp`}>
          Did the targeted criterion improve?
          <select id={`${id}-imp`} value={improved} onChange={(x) => setImproved(x.target.value as Tri)}>
            <option value="unknown">unknown</option>
            <option value="yes">yes</option>
            <option value="no">no</option>
          </select>
        </label>
        <label htmlFor={`${id}-wor`}>
          Did other criteria get worse?
          <select id={`${id}-wor`} value={worsened} onChange={(x) => setWorsened(x.target.value as Tri)}>
            <option value="unknown">unknown</option>
            <option value="yes">yes</option>
            <option value="no">no</option>
          </select>
        </label>
        <label>
          Lesson — explain in your own words
          <textarea rows={2} value={lesson} onChange={(x) => setLesson(x.target.value)} />
        </label>
        <div>
          <button type="submit">Save experiment notes</button> {saved && <span role="status">Saved.</span>}
        </div>
      </form>
    </details>
  );
}

export function KeeperControl({
  capture,
  shot,
  keeper,
  seqOf,
}: {
  capture: Capture;
  shot: Shot | null;
  keeper: Keeper | null;
  seqOf: (id: string | null | undefined) => number | string;
}) {
  const { run, refresh } = useApp();
  const [confirming, setConfirming] = useState(false);
  const [notes, setNotes] = useState("");
  if (!shot) {
    return <p className="small muted">This photo isn't assigned to a shot, so it can't be a keeper. Reassign it in the filmstrip.</p>;
  }
  const isKeeper = keeper?.capture_id === capture.id;
  return (
    <div className="keeper" data-testid="keeper">
      <h3>Keeper for {shot.title}</h3>
      {keeper ? (
        <p>
          Current keeper: <strong>photo #{seqOf(keeper.capture_id)}</strong>{" "}
          <span className="small muted">(accepted {new Date(keeper.accepted_at).toLocaleTimeString()} via {keeper.source})</span>{" "}
          <button
            type="button"
            onClick={() =>
              run("Revoke keeper", async () => {
                await api.revokeKeeper(shot.id);
                await refresh();
              })
            }
          >
            Revoke keeper
          </button>
        </p>
      ) : (
        <p className="small">No keeper yet — the shot stays unresolved until you accept one.</p>
      )}
      {!isKeeper &&
        (confirming ? (
          <form
            className="confirm"
            onSubmit={async (e) => {
              e.preventDefault();
              const r = await run("Accept keeper", () => api.acceptKeeper(shot.id, capture.id, notes.trim() || undefined));
              if (r) {
                setConfirming(false);
                setNotes("");
                await refresh();
              }
            }}
          >
            <p role="status">
              Accept photo #{capture.seq} as the keeper for <strong>{shot.title}</strong>?
              {keeper ? ` This replaces photo #${seqOf(keeper.capture_id)}.` : ""}
            </p>
            <label>
              Notes (optional)
              <input value={notes} onChange={(e) => setNotes(e.target.value)} />
            </label>
            <div className="button-row">
              <button type="submit" className="primary">
                Yes, accept photo #{capture.seq}
              </button>
              <button type="button" onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <button type="button" className="wide" onClick={() => setConfirming(true)}>
            Accept photo #{capture.seq} as keeper for {shot.title}
          </button>
        ))}
      {isKeeper && <p className="ok-line">✓ Photo #{capture.seq} is the accepted keeper.</p>}
    </div>
  );
}
