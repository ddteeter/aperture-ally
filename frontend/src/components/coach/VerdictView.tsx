import { useState } from "react";
import { api } from "../../api/client";
import type { Assessment, Capture, CriterionResult, SessionState, Shot } from "../../api/types";
import { useApp } from "../../AppContext";
import { useShortcuts } from "../../lib/keys";
import { criterionMeta, verdictMeta } from "../../ui/status";
import { criteriaSummary, modelLine, pickShowZone, seconds, startingPoint, verdictKind } from "./model";
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

/** The next shot to work on after this one: the first unresolved shot after it, wrapping round. */
export function nextShotTitle(state: SessionState | null, shotId: string | null): string | null {
  if (!state) return null;
  const order = state.coverage.shots;
  const i = order.findIndex((c) => c.shot_id === shotId);
  const rotated = [...order.slice(i + 1), ...order.slice(0, Math.max(i, 0))];
  const next = rotated.find((c) => !c.resolved && c.shot_id !== shotId);
  return next ? state.shots.find((s) => s.id === next.shot_id)?.title ?? null : null;
}

function clock(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Retake / usable candidate / uncertain verdict for a single-photo assessment. */
export function VerdictView({ capture, a, shot }: { capture: Capture; a: Assessment; shot: Shot | null }) {
  const { state } = useApp();
  const r = a.result!;
  const pa = r.primary_action;
  const kind = verdictKind(r);
  const base = verdictMeta(r.verdict);
  const meta = kind === "usable" ? { ...base, word: "Usable" } : kind === "usable_but" ? { ...base, word: "Usable, but…" } : base;
  const sp = startingPoint(a.exposure_note);
  const show = pickShowZone(r);
  const [causes, setCauses] = useState(false);
  const [why, setWhy] = useState(false);
  const [saw, setSaw] = useState(false);
  useShortcuts((sc, e) => {
    if (sc.kind === "saw" && !e.defaultPrevented) {
      setSaw(true);
      return true;
    }
    return false;
  });
  const correction = a.early_speech?.corrected ? a.early_speech : null;
  const next = kind === "usable" ? nextShotTitle(state, shot?.id ?? null) : null;
  const sub = [
    `Photo #${capture.seq}`,
    kind === "usable_but" ? "fine to keep · one change would help" : kind === "usable" ? "no change needed" : null,
    kind !== "usable_but" && seconds(a.timings?.total_ms) && `verdict in ${seconds(a.timings.total_ms)}`,
    speechWord(a.speech_status),
  ]
    .filter(Boolean)
    .join(" · ");

  const showMe = () =>
    show && window.dispatchEvent(new CustomEvent("aa:show-zone", { detail: { regionId: show.regionId, zone: show.zone } }));

  return (
    <>
      {correction && (
        <div role="alert" className="cp-correction" data-testid="correction">
          <span className="cp-correction-label">! CORRECTION{a.completed_at ? ` · SPOKEN ${clock(a.completed_at)}` : ""}</span>
          <span className="cp-correction-text">{r.spoken_text}</span>
          <span className="cp-correction-was">
            Earlier I said <s>“{correction.text}”</s>. The full check changed the advice.
          </span>
        </div>
      )}
      <GlanceHead meta={meta} sub={sub} tag={honestyTag(a, state?.session.simulated)} />

      {pa && (
        <div className="cp-stack cp-gap-8">
          <Label>{kind === "usable_but" ? "One change at the camera · optional" : "Do this"}</Label>
          <p className="cp-do">{pa.instruction}</p>
          {sp && <StartingPointLine sp={sp} />}
        </div>
      )}
      {kind === "usable" && (
        <div className="cp-stack cp-gap-8" data-testid="nothing-to-change">
          <Label>Nothing to change</Label>
          <p className="cp-do">Keep it.{next ? ` Next: ${next}.` : ""}</p>
        </div>
      )}

      {pa && (
        <button type="button" className="cp-disclosure" aria-expanded={why} onClick={() => setWhy((v) => !v)}>
          {why ? "▾" : "▸"} Why, and what to expect
        </button>
      )}
      {pa && why && (
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
          <Label>Probably fixable in post · no need to reshoot</Label>
          <ul className="cp-post">
            {r.fixable_in_post!.map((c, i) => (
              <li key={i}>
                <span className="cp-post-g" aria-hidden="true">~</span>
                {c}
              </li>
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

      <button type="button" className="cp-disagree" aria-keyshortcuts="Meta+I" onClick={() => setSaw(true)}>
        <span>Disagree? See what the coach saw</span>
        <span className="cp-kbd-t">⌘I</span>
      </button>
      <p className="cp-model" data-testid="coach-meta">
        {modelLine(a)}
      </p>
      {saw && <CoachSaw a={a} capture={capture} shot={shot} onClose={() => setSaw(false)} />}
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
