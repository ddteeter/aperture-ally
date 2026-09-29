import { useState } from "react";
import { api } from "../../api/client";
import type { Assessment, Capture, CriterionResult, Shot } from "../../api/types";
import { useApp } from "../../AppContext";
import { criterionMeta, verdictMeta } from "../../ui/status";
import { criteriaSummary, modelLine, pickShowZone, seconds, startingPoint } from "./model";
import { CoachSaw } from "./CoachSaw";
import { GlanceHead, Label } from "./parts";

/** Tag shown next to the verdict when the coach is not a real model or the session is replayed. */
export function honestyTag(a: Assessment, simulated: boolean | undefined): string | null {
  if (simulated) return "SIMULATED";
  return a.provider === "mock" ? "MOCK" : null;
}

export function speechWord(s: string | null | undefined): string | null {
  if (!s) return null;
  return { spoken: "spoken", pending: "speaking soon", suppressed: "not spoken", cancelled: "speech stopped", failed: "speech failed" }[s] ?? null;
}

/** Retake / usable candidate / uncertain verdict for a single-photo assessment. */
export function VerdictView({ capture, a, shot }: { capture: Capture; a: Assessment; shot: Shot | null }) {
  const { state } = useApp();
  const r = a.result!;
  const pa = r.primary_action;
  const meta = verdictMeta(r.verdict);
  const sp = startingPoint(a.exposure_note);
  const show = pickShowZone(r);
  const [causes, setCauses] = useState(false);
  const [saw, setSaw] = useState(false);
  const sub = [`Photo #${capture.seq}`, seconds(a.timings?.total_ms) && `verdict in ${seconds(a.timings.total_ms)}`, speechWord(a.speech_status)]
    .filter(Boolean)
    .join(" · ");

  const showMe = () =>
    show && window.dispatchEvent(new CustomEvent("aa:show-zone", { detail: { regionId: show.regionId, zone: show.zone } }));

  return (
    <>
      <GlanceHead meta={meta} sub={sub} tag={honestyTag(a, state?.session.simulated)} />

      {pa && (
        <div className="cp-stack cp-gap-8">
          <Label>Do this</Label>
          <p className="cp-do">{pa.instruction}</p>
          {sp && <StartingPointLine sp={sp} />}
        </div>
      )}

      {pa && (
        <dl className="cp-kv">
          <dt className="cp-label">Why</dt>
          <dd>
            {pa.explanation}{" "}
            {show && (
              <button type="button" className="cp-link" onClick={showMe}>
                Show me on the photo ↙
              </button>
            )}
          </dd>
          <dt className="cp-label">Expect</dt>
          <dd>{pa.expected_effect}</dd>
          {pa.tradeoff && (
            <>
              <dt className="cp-label">Tradeoff</dt>
              <dd className="cp-t2">{pa.tradeoff}</dd>
            </>
          )}
          {pa.hold_constant && (
            <>
              <dt className="cp-label">Keep</dt>
              <dd className="cp-t2">{pa.hold_constant}</dd>
            </>
          )}
          {pa.prerequisites.length > 0 && (
            <>
              <dt className="cp-label">Only if</dt>
              <dd className="cp-t2">{pa.prerequisites.join("; ")}</dd>
            </>
          )}
        </dl>
      )}

      {r.question_for_user && <CoachAsks question={r.question_for_user} captureId={capture.id} />}

      <CriteriaList results={r.criterion_results} shot={shot} />

      {r.teaching_prompt && (
        <div className="cp-card">
          <Label>Try this</Label>
          <p className="cp-body-text">{r.teaching_prompt}</p>
        </div>
      )}

      <Warnings warnings={a.warnings} />

      {(r.fixable_in_post?.length ?? 0) > 0 && (
        <div className="cp-stack cp-gap-6" data-testid="fixable-in-post">
          <Label>Probably fixable in post</Label>
          <ul className="cp-causes">
            {r.fixable_in_post!.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {r.alternative_causes.length > 0 && (
        <div className="cp-stack cp-gap-6">
          <button type="button" className="cp-disclosure" aria-expanded={causes} onClick={() => setCauses((v) => !v)}>
            {causes ? "▾" : "▸"} Other possible causes ({r.alternative_causes.length})
          </button>
          {causes && (
            <ul className="cp-causes">
              {r.alternative_causes.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <p className="cp-model" data-testid="coach-meta">
        {modelLine(a)}{" "}
        <button type="button" className="cp-link" onClick={() => setSaw(true)}>
          What the coach saw
        </button>
      </p>
      {saw && <CoachSaw assessmentId={a.id} captureId={a.capture_id} onClose={() => setSaw(false)} />}
    </>
  );
}

export function StartingPointLine({ sp }: { sp: NonNullable<ReturnType<typeof startingPoint>> }) {
  if (sp.kind === "none") {
    return <p className="cp-note">Starting point not calculated: {sp.reason}</p>;
  }
  return (
    <div className="cp-start">
      <Label>Starting point</Label>
      <span className="cp-start-val">{sp.value}</span>
      {sp.detail && <span className="cp-start-detail">{sp.detail}</span>}
    </div>
  );
}

export function CoachAsks({ question, captureId }: { question: string; captureId: string }) {
  const { sid, run, toast } = useApp();
  const [text, setText] = useState("");
  const id = `ask-${captureId}`;
  return (
    <div className="cp-ask">
      <Label tone="var(--acc)">Coach asks</Label>
      <p className="cp-ask-q">{question}</p>
      <form
        className="cp-ask-form"
        onSubmit={async (e) => {
          e.preventDefault();
          const t = text.trim();
          if (!t) return;
          const r = await run("Answer the coach", () => api.voiceText({ text: t, session_id: sid, capture_id: captureId }));
          if (r) {
            setText("");
            toast({ glyph: "✓", text: "Answer sent", source: "KEYBOARD" });
          }
        }}
      >
        <label htmlFor={id} className="cp-hint">
          Answer by voice (hold the remote) or type
        </label>
        <div className="cp-row">
          <input id={id} className="cp-input" value={text} maxLength={500} onChange={(e) => setText(e.target.value)} />
          <button type="submit" className="cp-btn cp-btn-s" disabled={!text.trim()}>
            Send
          </button>
        </div>
      </form>
    </div>
  );
}

export function CriteriaList({ results, shot }: { results: CriterionResult[]; shot: Shot | null }) {
  if (!results.length) return null;
  const text = (id: string) => shot?.criteria.find((c) => c.id === id)?.text ?? id;
  return (
    <div className="cp-stack">
      <div className="cp-split">
        <Label>Criteria</Label>
        <span className="cp-hint">{criteriaSummary(results)}</span>
      </div>
      <ul className="cp-crit" aria-label="Criteria">
        {results.map((cr) => {
          const m = criterionMeta(cr.result);
          return (
            <li key={cr.criterion_id}>
              <span className="cp-crit-g" style={{ background: m.tint, color: m.color }} aria-hidden="true">
                {m.glyph}
              </span>
              <span className="cp-crit-t">
                {text(cr.criterion_id)}
                {cr.evidence && <span className="cp-crit-e">{cr.evidence}</span>}
              </span>
              <span className="cp-crit-w" style={{ color: m.color }}>
                {m.word}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function Warnings({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return (
    <ul className="cp-warns">
      {warnings.map((w, i) => (
        <li key={i}>
          <span className="cp-warn-g" aria-hidden="true">
            ⚠
          </span>
          <span>
            <span className="cp-sr">Warning: </span>
            {w}
          </span>
        </li>
      ))}
    </ul>
  );
}
