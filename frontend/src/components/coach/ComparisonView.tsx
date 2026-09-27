import { useEffect, useState } from "react";
import { api, imageUrl } from "../../api/client";
import type { Assessment, BaselineCandidate, Capture, Experiment, ScopeDelta, Shot } from "../../api/types";
import { useApp } from "../../AppContext";
import { Histogram } from "../../ui/Histogram";
import { comparisonMeta, criterionMeta, verdictMeta } from "../../ui/status";
import { TONE_COLOR, evLabel, modelLine, regionPair, startingPoint, whatChanged, type ChangeRow } from "./model";
import { GlanceHead, Label } from "./parts";
import { StartingPointLine, Warnings, honestyTag } from "./VerdictView";

export interface ComparisonViewProps {
  capture: Capture;
  a: Assessment;
  shot: Shot | null;
  captures: Capture[];
  experiment: Experiment | null;
}

/** Retake compared with its baseline: improved / worse / mixed / can't compare. */
export function ComparisonView({ capture, a, shot, captures, experiment }: ComparisonViewProps) {
  const { state } = useApp();
  const r = a.result!;
  const outcome = r.comparison?.outcome ?? "uncertain";
  const meta = comparisonMeta(outcome);
  const m = capture.comparison_metrics ?? null;
  const baselineId = r.comparison?.baseline_capture_id ?? a.baseline_capture_id ?? m?.baseline_capture_id ?? capture.baseline_capture_id;
  const baseline = captures.find((c) => c.id === baselineId) ?? null;
  const bSeq = baseline?.seq ?? m?.baseline_seq ?? "?";
  const after = verdictMeta(r.verdict);
  const uncertain = outcome === "uncertain";
  const framing = m?.framing ?? null;
  const comparable = framing ? framing.comparable : !uncertain;

  const sub = uncertain
    ? `#${capture.seq} vs #${bSeq} · ${after.word.toLowerCase()}`
    : `#${capture.seq} compared with #${bSeq} · ${after.word.toLowerCase()}`;
  const summary = r.comparison?.evidence || r.spoken_text;

  let changes: ChangeRow[] = [];
  if (m) changes = whatChanged(m);
  else if (capture.histogram_changes?.changes.length)
    changes = capture.histogram_changes.changes.map((c) => ({ glyph: "·", tone: "t3", label: c, value: "" }));

  const sp = startingPoint(a.exposure_note);
  const quote = capture.user_reported_change || experiment?.actual_change || null;

  return (
    <>
      <GlanceHead meta={meta} sub={sub} tag={honestyTag(a, state?.session.simulated)} />
      <div className="cp-cmp-bar" data-testid="comparison">
        <span className="cp-sr">
          Comparison vs #{bSeq}: {meta.word}.
        </span>
        <BaselinePicker capture={capture} baselineSeq={bSeq} defaultOpen={uncertain} />
        {framing && (
          <span className="cp-match" style={{ color: framing.comparable ? "var(--t3)" : "var(--unc)" }}>
            Framing match {Math.round(framing.score * 100)}%{framing.comparable ? "" : " · too low"}
          </span>
        )}
      </div>

      {summary && <p className="cp-summary">{summary}</p>}

      {(changes.length > 0 || m?.ev_delta != null) && (
        <div className="cp-stack">
          <Label>What changed</Label>
          <ul className="cp-changes">
            {changes.map((x, i) => (
              <li key={i}>
                <span className="cp-change-g" style={{ color: TONE_COLOR[x.tone] }} aria-hidden="true">
                  {x.glyph}
                </span>
                <span className="cp-change-l">{x.label}</span>
                {x.value && <span className="cp-change-v">{x.value}</span>}
              </li>
            ))}
            {m?.ev_delta != null && (
              <li className="cp-change-ev">
                <span className="cp-change-l">{m.ev_note || "Exposure change from the camera settings"}</span>
                <span className="cp-change-v">{evLabel(m.ev_delta)}</span>
              </li>
            )}
          </ul>
        </div>
      )}

      {m && m.regions.length > 0 && baselineId && (
        <div className="cp-stack">
          <Label>Regions · before → after</Label>
          <div className="cp-pairs">
            {m.regions.map((d) => (
              <RegionPair key={d.scope} d={d} comparable={comparable} baselineId={baselineId} captureId={capture.id} bSeq={bSeq} seq={capture.seq} />
            ))}
          </div>
          <p className="cp-hint">
            Outline = #{bSeq}, bars = #{capture.seq}. Sharpness is relative to the baseline. From JPEG previews, not RAW.
          </p>
        </div>
      )}

      <CriteriaDelta shot={shot} before={baseline?.latest_assessment ?? null} after={a} bSeq={bSeq} seq={capture.seq} ownOnly={uncertain} />

      {outcome !== "improved" && r.primary_action && (
        <div className="cp-next">
          <Label>Next</Label>
          <p className="cp-next-t">{r.primary_action.instruction}</p>
          {sp && <StartingPointLine sp={sp} />}
        </div>
      )}

      <Warnings warnings={a.warnings} />

      <ChangedQuote quote={quote} capture={capture} experiment={experiment} />

      {experiment && <AdviceRating e={experiment} bSeq={bSeq} />}

      <p className="cp-model" data-testid="coach-meta">
        {modelLine(a)}
      </p>
    </>
  );
}

function RegionPair({
  d,
  comparable,
  baselineId,
  captureId,
  bSeq,
  seq,
}: {
  d: ScopeDelta;
  comparable: boolean;
  baselineId: string;
  captureId: string;
  bSeq: number | string;
  seq: number;
}) {
  const v = regionPair(d, comparable);
  return (
    <div className="cp-pair">
      <div className="cp-split">
        <span className="cp-pair-name">{d.label}</span>
        <span className="cp-pair-w" style={{ color: TONE_COLOR[v.tone] }}>
          <span aria-hidden="true">{v.glyph}</span> {v.word}
        </span>
      </div>
      <div className="cp-pair-imgs">
        <img src={imageUrl(baselineId, `crop_${d.scope}`)} alt={`${d.label} in #${bSeq} (before)`} loading="lazy" />
        <img src={imageUrl(captureId, `crop_${d.scope}`)} alt={`${d.label} in #${seq} (after)`} loading="lazy" />
      </div>
      {d.histogram_after && (
        <Histogram
          bins={d.histogram_after}
          previous={d.histogram_before}
          clipHigh={d.highlight_clip_after}
          clipLow={d.shadow_clip_after}
          height={36}
          labels={false}
          label={`${d.label} brightness, #${bSeq} outline vs #${seq} bars`}
        />
      )}
      <p className="cp-pair-s">{v.sentence}</p>
    </div>
  );
}

function CriteriaDelta({
  shot,
  before,
  after,
  bSeq,
  seq,
  ownOnly,
}: {
  shot: Shot | null;
  before: Assessment | null;
  after: Assessment;
  bSeq: number | string;
  seq: number;
  ownOnly: boolean;
}) {
  const results = after.result?.criterion_results ?? [];
  if (!results.length) return null;
  const prev = ownOnly ? [] : before?.status === "completed" ? before.result?.criterion_results ?? [] : [];
  const text = (id: string) => shot?.criteria.find((c) => c.id === id)?.text ?? id;
  return (
    <div className="cp-stack cp-gap-6">
      <Label>{ownOnly ? `Criteria · #${seq} on its own` : `Criteria #${bSeq} → #${seq}`}</Label>
      <ul className="cp-crit-delta" aria-label="Criteria before and after">
        {results.map((cr) => {
          const b = prev.find((p) => p.criterion_id === cr.criterion_id);
          const bm = criterionMeta(b?.result);
          const am = criterionMeta(cr.result);
          return (
            <li key={cr.criterion_id}>
              <span style={{ color: bm.color }} title={`#${bSeq}: ${bm.word}`}>
                <span aria-hidden="true">{bm.glyph}</span>
                <span className="cp-sr">#{bSeq} {bm.word}</span>
              </span>
              <span className="cp-arrow" aria-hidden="true">
                →
              </span>
              <span style={{ color: am.color }} title={`#${seq}: ${am.word}`}>
                <span aria-hidden="true">{am.glyph}</span>
                <span className="cp-sr">#{seq} {am.word}</span>
              </span>
              <span className="cp-crit-t">{text(cr.criterion_id)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ChangedQuote({ quote, capture, experiment }: { quote: string | null; capture: Capture; experiment: Experiment | null }) {
  const { run, refresh, toast } = useApp();
  const [text, setText] = useState("");
  if (quote) {
    return (
      <div className="cp-card">
        <Label>What you changed</Label>
        <p className="cp-body-text">“{quote}”</p>
      </div>
    );
  }
  const id = `chg-${capture.id}`;
  return (
    <form
      className="cp-card"
      onSubmit={async (e) => {
        e.preventDefault();
        const t = text.trim();
        if (!t) return;
        const ok = await run("Save what you changed", async () => {
          if (experiment) await api.patchExperiment(experiment.id, { actual_change: t });
          else await api.patchCapture(capture.id, { user_reported_change: t });
          return true;
        });
        if (ok) {
          setText("");
          toast({ glyph: "✓", text: `Change noted: ${t}`, source: "KEYBOARD" });
          await refresh();
        }
      }}
    >
      <label className="cp-label" htmlFor={id}>
        What you changed for #{capture.seq}
      </label>
      <div className="cp-row">
        <input id={id} className="cp-input" value={text} maxLength={500} onChange={(e) => setText(e.target.value)} placeholder="Not recorded yet" />
        <button type="submit" className="cp-btn cp-btn-s" disabled={!text.trim()}>
          Save
        </button>
      </div>
    </form>
  );
}

const RATINGS = [
  { id: "helpful", glyph: "✓", label: "Helpful" },
  { id: "neutral", glyph: "–", label: "Neutral" },
  { id: "harmful", glyph: "✕", label: "Harmful" },
] as const;

function AdviceRating({ e, bSeq }: { e: Experiment; bSeq: number | string }) {
  const { run, refresh, toast } = useApp();
  const [rating, setRating] = useState(e.user_rating);
  const [lesson, setLesson] = useState(e.lesson ?? "");
  useEffect(() => setRating(e.user_rating), [e.user_rating]);
  const lessonId = `lesson-${e.id}`;

  const rate = async (id: (typeof RATINGS)[number]["id"], glyph: string) => {
    const r = await run("Rate advice", () => api.patchExperiment(e.id, { user_rating: id }));
    if (r) {
      setRating(id);
      toast({ glyph, text: `Marked ${id}`, source: "KEYBOARD", tone: id === "harmful" ? "ret" : id === "neutral" ? "neutral" : "ok" });
      await refresh();
    }
  };

  return (
    <>
      <div className="cp-stack cp-gap-8">
        <Label>Was the advice for #{bSeq}…</Label>
        <div className="cp-ratings" role="group" aria-label={`Was the advice for #${bSeq} helpful?`}>
          {RATINGS.map((x) => (
            <button
              key={x.id}
              type="button"
              className={`cp-rating${rating === x.id ? " is-on" : ""}`}
              aria-pressed={rating === x.id}
              onClick={() => void rate(x.id, x.glyph)}
            >
              <span aria-hidden="true">{x.glyph}</span>
              {x.label}
            </button>
          ))}
        </div>
      </div>
      <form
        className="cp-stack cp-gap-8"
        onSubmit={async (ev) => {
          ev.preventDefault();
          const r = await run("Save lesson", () => api.patchExperiment(e.id, { lesson: lesson.trim() || null }));
          if (r) {
            toast({ glyph: "✓", text: "Lesson saved", source: "KEYBOARD" });
            await refresh();
          }
        }}
      >
        <label className="cp-label" htmlFor={lessonId}>
          Lesson, in your words
        </label>
        <textarea id={lessonId} className="cp-textarea" rows={3} value={lesson} onChange={(x) => setLesson(x.target.value)} />
        <button type="submit" className="cp-btn cp-btn-s cp-self-start" disabled={lesson.trim() === (e.lesson ?? "")}>
          Save lesson
        </button>
      </form>
    </>
  );
}

function BaselinePicker({ capture, baselineSeq, defaultOpen }: { capture: Capture; baselineSeq: number | string; defaultOpen: boolean }) {
  const { run, refresh, toast } = useApp();
  const [open, setOpen] = useState(defaultOpen);
  const [cands, setCands] = useState<BaselineCandidate[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!open || cands) return;
    let alive = true;
    api
      .baselineCandidates(capture.id)
      .then((c) => alive && setCands(c))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [open, cands, capture.id]);

  const pick = async (c: BaselineCandidate) => {
    const r = await run("Compare with another photo", async () => {
      await api.patchCapture(capture.id, { baseline_capture_id: c.capture_id });
      return api.compare(capture.id, c.capture_id);
    });
    if (r) {
      setOpen(false);
      toast({ glyph: "◆", text: `Comparing #${capture.seq} with #${c.seq}`, source: "KEYBOARD", tone: "neutral" });
      await refresh();
    }
  };

  return (
    <div className="cp-picker">
      <button type="button" className="cp-btn cp-btn-s" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        Compare with… <strong>#{baselineSeq}</strong> <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="cp-picker-pop">
          <span className="cp-label">Compare with… · this shot</span>
          {failed && <p className="cp-hint">Couldn’t load earlier photos.</p>}
          {!failed && !cands && <p className="cp-hint">Loading…</p>}
          {cands?.length === 0 && <p className="cp-hint">No other photos of this shot yet.</p>}
          {cands?.map((c) => {
            const vm = verdictMeta(c.verdict);
            return (
              <button
                key={c.capture_id}
                type="button"
                className={`cp-pick${c.is_current_baseline ? " is-on" : ""}`}
                aria-current={c.is_current_baseline || undefined}
                onClick={() => void pick(c)}
              >
                <img src={imageUrl(c.capture_id, "thumb")} alt="" />
                <span className="cp-pick-t">
                  <span className="cp-pick-n">
                    #{c.seq} · {vm.word}
                  </span>
                  <span className="cp-pick-m">
                    {c.framing ? `framing ${Math.round(c.framing.score * 100)}%${c.framing.comparable ? "" : " · too low"}` : "framing not measured"}
                  </span>
                </span>
                <span style={{ color: vm.color }} aria-hidden="true">
                  {vm.glyph}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
