import { useRef, useState } from "react";
import { api } from "../api/client";
import type { Capture, Experiment, Keeper, Shot } from "../api/types";
import { useApp } from "../AppContext";
import { isAnalysing } from "../lib/format";
import { ComparisonView } from "./coach/ComparisonView";
import { CameraExif, ChangeNoteInput, KeeperActions, type KeeperMode } from "./coach/Footer";
import { KeeperDialog } from "./coach/KeeperDialog";
import { AnalysingView, BadFileCard, BriefView, FailureCard, IngestNotices, NoVerdict, PausedCard } from "./coach/States";
import { useKey } from "./coach/useKey";
import { VerdictView } from "./coach/VerdictView";
import "./coach.css";

export interface CoachPanelProps {
  capture: Capture | null;
  shot: Shot | null;
  captures: Capture[];
  experiments: Experiment[];
  keeper: Keeper | null;
}

export type CoachMode = "brief" | "analysing" | "verdict" | "comparison" | "failure" | "bad_file" | "no_verdict";

/** Which body the panel shows for the selected capture. */
export function coachMode(capture: Capture | null): CoachMode {
  if (!capture) return "brief";
  if (isAnalysing(capture)) return "analysing";
  const la = capture.latest_assessment;
  if (la?.status === "completed" && la.result) return la.kind === "compare" && la.result.comparison ? "comparison" : "verdict";
  if (la?.status === "failed") return "failure";
  if (capture.processing_state === "failed") return "bad_file";
  return "no_verdict";
}

export function CoachPanel({ capture, shot, captures, experiments, keeper }: CoachPanelProps) {
  const { state, run, refresh, toast } = useApp();
  const [confirming, setConfirming] = useState(false);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const changeRef = useRef<HTMLInputElement>(null);

  const mode = coachMode(capture);
  const la = capture?.latest_assessment ?? null;
  const session = state?.session;
  const paused = !!session && (session.coaching_paused || !!state?.usage?.exceeded);
  const activeShot = state?.shots.find((s) => s.id === session?.active_shot_id) ?? null;
  const briefShot = shot ?? activeShot;
  const experiment =
    (capture && experiments.find((e) => e.follow_up_capture_id === capture.id)) ??
    (la && experiments.find((e) => e.comparison_assessment_id === la.id)) ??
    null;

  const seqOf = (id: string | null | undefined) => captures.find((c) => c.id === id)?.seq ?? null;
  const isKeeper = !!capture && keeper?.capture_id === capture.id;
  const usable = la?.status === "completed" && la.result?.verdict === "usable_candidate";
  const keeperMode: KeeperMode =
    !capture || !shot || capture.processing_state === "failed"
      ? { kind: "none" }
      : isKeeper
        ? { kind: "accepted", seq: capture.seq }
        : { kind: "offer", seq: capture.seq, primary: usable && mode !== "analysing" };

  useKey(
    { key: "Enter", mod: true },
    (e) => {
      e.preventDefault();
      setConfirming(true);
    },
    keeperMode.kind === "offer" && !confirming,
  );

  const accept = async (notes: string) => {
    if (!capture || !shot) return;
    const r = await run("Accept keeper", () => api.acceptKeeper(shot.id, capture.id, notes.trim() || undefined));
    if (r) {
      setConfirming(false);
      toast({ glyph: "★", text: `Keeper accepted · #${capture.seq}`, source: "KEYBOARD", tone: "neutral" });
      await refresh();
    }
  };
  const undo = async () => {
    if (!shot || !capture) return;
    const r = await run("Revoke keeper", () => api.revokeKeeper(shot.id));
    if (r) {
      toast({ glyph: "↺", text: `Keeper revoked · #${capture.seq}`, source: "KEYBOARD", tone: "neutral" });
      await refresh();
    }
  };

  const heading = capture ? `Coach — photo #${capture.seq}` : "Coach";
  const spoken = mode === "verdict" || mode === "comparison" ? la?.result?.spoken_text : null;

  return (
    <section className="cp" aria-labelledby="coach-h" data-testid="coach-panel">
      <h2 id="coach-h" className="cp-sr">
        {heading}
      </h2>
      {/* Always present so new advice is announced; the visible text is below. */}
      <div aria-live="polite" aria-atomic="true" className="cp-sr" data-testid="coach-spoken">
        {mode === "analysing" ? `Analysing photo #${capture?.seq}…` : spoken}
      </div>

      <div className="cp-body">
        {paused && <PausedCard />}
        <IngestNotices capture={capture} pending={state?.pending_files ?? []} />

        {mode === "brief" &&
          (briefShot ? <BriefView shot={briefShot} /> : <p className="cp-hint">Pick a shot to see its brief.</p>)}
        {mode === "analysing" && capture && <AnalysingView capture={capture} la={la} shot={shot} />}
        {mode === "verdict" && capture && la && <VerdictView capture={capture} a={la} shot={shot} />}
        {mode === "comparison" && capture && la && (
          <ComparisonView capture={capture} a={la} shot={shot} captures={captures} experiment={experiment} />
        )}
        {mode === "failure" && capture && la && <FailureCard capture={capture} la={la} />}
        {mode === "bad_file" && capture && dismissed !== capture.id && (
          <BadFileCard capture={capture} onDismiss={() => setDismissed(capture.id)} />
        )}
        {mode === "no_verdict" && capture && <NoVerdict capture={capture} paused={paused} />}

        {capture && !shot && mode !== "bad_file" && (
          <p className="cp-hint">This photo isn’t assigned to a shot, so it can’t be a keeper. Reassign it in the filmstrip.</p>
        )}
        {capture && mode !== "bad_file" && <CameraExif capture={capture} />}
      </div>

      <div className="cp-foot">
        <KeeperActions
          mode={keeperMode}
          onOpen={() => setConfirming(true)}
          onUndo={() => void undo()}
          onTakeAnother={() => changeRef.current?.focus()}
        />
        <ChangeNoteInput inputRef={changeRef} />
        {mode === "failure" && <p className="cp-hint">Your photos are safe. Only the coach is unavailable.</p>}
        {mode === "bad_file" && <p className="cp-hint">File problems never block the next shot.</p>}
      </div>

      {confirming && capture && shot && (
        <KeeperDialog
          capture={capture}
          shot={shot}
          replacesSeq={keeper && keeper.capture_id !== capture.id ? seqOf(keeper.capture_id) : null}
          onAccept={(n) => void accept(n)}
          onClose={() => setConfirming(false)}
        />
      )}
    </section>
  );
}
