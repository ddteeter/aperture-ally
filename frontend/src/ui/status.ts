// Status vocabulary from the design system: every status is a glyph + a word + a colour token.
// Colour is never the only signal. Colours are CSS variables so both themes work.
import type { ComparisonOutcome, CoverageState, CriterionOutcome, InsightSeverity, Verdict } from "../api/types";

export interface StatusMeta {
  glyph: string;
  word: string;
  /** Foreground colour (CSS value). */
  color: string;
  /** Tinted background (CSS value). */
  tint: string;
}

const OK = { color: "var(--ok)", tint: "var(--ok-t)" };
const RET = { color: "var(--ret)", tint: "var(--ret-t)" };
const UNC = { color: "var(--unc)", tint: "var(--unc-t)" };
const ACC = { color: "var(--acc)", tint: "var(--acc-t)" };
const MUTED = { color: "var(--t3)", tint: "var(--raised)" };
const INK = { color: "var(--t1)", tint: "var(--raised)" };

export const VERDICT: Record<string, StatusMeta> = {
  usable_candidate: { glyph: "✓", word: "Usable candidate", ...OK },
  needs_retake: { glyph: "↺", word: "Needs retake", ...RET },
  uncertain: { glyph: "?", word: "Uncertain", ...UNC },
};
export function verdictMeta(v: Verdict | null | undefined): StatusMeta {
  return (v && VERDICT[v]) || { glyph: "–", word: "No verdict", ...MUTED };
}

export const COMPARISON: Record<string, StatusMeta> = {
  improved: { glyph: "▲", word: "Improved", ...OK },
  worse: { glyph: "▼", word: "Worse", ...RET },
  mixed: { glyph: "◆", word: "Mixed", ...UNC },
  uncertain: { glyph: "?", word: "Can’t compare", ...UNC },
};
export function comparisonMeta(o: ComparisonOutcome | null | undefined): StatusMeta {
  return (o && COMPARISON[o]) || COMPARISON.uncertain;
}

export const CRITERION: Record<string, StatusMeta> = {
  pass: { glyph: "✓", word: "Pass", ...OK },
  fail: { glyph: "✕", word: "Fail", ...RET },
  uncertain: { glyph: "?", word: "Unsure", ...UNC },
};
export function criterionMeta(r: CriterionOutcome | null | undefined): StatusMeta {
  return (r && CRITERION[r]) || { glyph: "—", word: "Not checked", ...MUTED };
}

/** Shot / coverage states (shot rail, coverage cards). */
export const SHOT_STATE: Record<string, StatusMeta> = {
  missing: { glyph: "○", word: "Missing", ...MUTED },
  candidate: { glyph: "✓", word: "Candidate", ...OK },
  needs_retake: { glyph: "↺", word: "Needs retake", ...RET },
  accepted: { glyph: "★", word: "Keeper", ...INK },
  uncertain: { glyph: "?", word: "Uncertain", ...UNC },
};
export function shotStateMeta(s: CoverageState | null | undefined): StatusMeta {
  return (s && SHOT_STATE[s]) || SHOT_STATE.missing;
}

/** Filmstrip / capture-level states that are not verdicts. */
export const CAPTURE_STATE: Record<string, StatusMeta> = {
  analysing: { glyph: "…", word: "Analysing", ...ACC },
  failed: { glyph: "!", word: "AI unavailable", ...RET },
  bad_file: { glyph: "⚠", word: "Bad file", ...RET },
  unsupported: { glyph: "⚠", word: "RAW-only · no preview", ...RET },
  writing: { glyph: "◌", word: "Still being written", ...ACC },
  maybe_other_shot: { glyph: "?", word: "Might belong to previous shot", ...UNC },
  no_verdict: { glyph: "–", word: "No verdict", ...MUTED },
  keeper: { glyph: "★", word: "Keeper", ...INK },
};

export const SEVERITY: Record<InsightSeverity, StatusMeta> = {
  problem: { glyph: "✕", word: "Detail lost", ...RET },
  warn: { glyph: "!", word: "Check", ...UNC },
  info: { glyph: "i", word: "Note", ...MUTED },
  ok: { glyph: "✓", word: "OK", ...OK },
};
