import { useState } from "react";
import { api, imageUrl } from "../api/client";
import type { CoverageShot } from "../api/types";
import { useApp } from "../AppContext";
import { shotStateMeta } from "../ui/status";
import "./workflows.css";
import { coverageCounts, coverageCta, coverageHeadline, coverageMeta, exportLabel, fileName } from "./workflowsLogic";

const EXPORT_FORMATS = [
  { label: "JSON", desc: "Full session data for the blog tooling" },
  { label: "Markdown", desc: "Shot notes, verdicts and lessons" },
  { label: "Contact sheet", desc: "One JPEG image of keepers, 3 × 3" },
];

export function CoverageTab() {
  const { sid, state, run, refresh, toast } = useApp();
  const [exported, setExported] = useState<Record<string, string> | null>(null);
  const [exporting, setExporting] = useState(false);
  const [asking, setAsking] = useState<string | null>(null);
  if (!state || !sid) return null;
  const cov = state.coverage;
  const counts = coverageCounts(cov.shots);
  const unresolved = cov.total - cov.resolved;

  const goShoot = async (shotId: string) => {
    await run("Set active shot", () => api.setActiveShot(sid, shotId));
    await refresh();
    window.location.hash = "shoot";
  };

  const revoke = async (s: CoverageShot) => {
    setAsking(null);
    const r = await run("Revoke keeper", () => api.revokeKeeper(s.shot_id));
    if (r) {
      toast({ glyph: "↺", text: `#${s.keeper?.capture_seq ?? "?"} is a candidate again`, source: "COVERAGE", tone: "neutral" });
      await refresh();
    }
  };

  const doExport = async () => {
    setExporting(true);
    const r = await run("Export", () => api.exports(sid));
    setExporting(false);
    if (r) setExported(r);
  };

  return (
    <div className="wf-screen wf-split wf-split-aside-360">
      <div className="wf-main">
        <div className="wf-cov-head">
          <div className="wf-stack-6">
            <span className="wf-eyebrow">COVERAGE · AM I DONE?</span>
            <h2 className="wf-headline" id="cov-h">
              {coverageHeadline(cov)}
            </h2>
            <span className="wf-t2 wf-small">
              {cov.resolved} of {cov.total} shots have a keeper · AI verdicts are advisory; only accepted keepers resolve a shot.
            </span>
          </div>
          <ul className="wf-counts" aria-label="Counts">
            <li>
              <span className="wf-mono" aria-hidden="true">★</span> {counts.keepers} {counts.keepers === 1 ? "keeper" : "keepers"}
            </li>
            <li className="wf-ok">
              <span className="wf-mono" aria-hidden="true">✓</span> {counts.candidates} {counts.candidates === 1 ? "candidate" : "candidates"}
            </li>
            <li className="wf-ret">
              <span className="wf-mono" aria-hidden="true">↺</span> {counts.retakes} {counts.retakes === 1 ? "needs retake" : "need retakes"}
            </li>
            <li className="wf-t3">
              <span className="wf-mono" aria-hidden="true">○</span> {counts.missing} missing
            </li>
          </ul>
        </div>

        {cov.shots.length === 0 ? (
          <p className="wf-t2">This session has no shots. Add some on the Shot list tab.</p>
        ) : (
          <ul className="wf-cov-grid" aria-labelledby="cov-h">
            {cov.shots.map((s, i) => {
              const st = shotStateMeta(s.state);
              const latest = [...state.captures].reverse().find((c) => c.shot_id === s.shot_id);
              const thumbId = s.keeper?.capture_id ?? latest?.id ?? null;
              const isKeeper = s.state === "accepted" && !!s.keeper;
              return (
                <li key={s.shot_id} className="wf-card wf-cov-card" data-testid={`coverage-row-${s.title}`}>
                  <div className="wf-cov-thumb">
                    {thumbId ? (
                      <img src={imageUrl(thumbId, "thumb")} alt={s.keeper ? `Keeper #${s.keeper.capture_seq ?? "?"}` : "Latest attempt"} />
                    ) : (
                      <span className="wf-mono wf-t3 wf-xs">no keeper</span>
                    )}
                    <span className="wf-status-tag" style={{ color: st.color }}>
                      <span className="wf-mono" aria-hidden="true">{st.glyph}</span> {st.word}
                    </span>
                  </div>
                  <div className="wf-cov-body">
                    <div className="wf-row-baseline">
                      <span className="wf-mono wf-t3 wf-xs">{i + 1}</span>
                      <span className="wf-cov-title">{s.title}</span>
                    </div>
                    <span className="wf-t2 wf-xs">{coverageMeta(s, state.captures)}</span>
                    {s.keeper_problem && (
                      <span className="wf-warn-line wf-xs" role="note">
                        <span className="wf-mono" aria-hidden="true">!</span> {s.keeper_problem}
                      </span>
                    )}
                    <div className="wf-cov-actions">
                      <a
                        href="#shoot"
                        className="wf-link"
                        aria-label={`${coverageCta(s.state).replace(" →", "")}: ${s.title}`}
                        onClick={(e) => {
                          e.preventDefault();
                          void goShoot(s.shot_id);
                        }}
                      >
                        {coverageCta(s.state)}
                      </a>
                      {isKeeper && asking !== s.shot_id && (
                        <button type="button" className="wf-btn-text wf-push" onClick={() => setAsking(s.shot_id)}>
                          Revoke keeper
                        </button>
                      )}
                    </div>
                    {isKeeper && asking === s.shot_id && (
                      <div className="wf-confirm" role="group" aria-label="Confirm revoke">
                        <span>
                          Revoke #{s.keeper!.capture_seq ?? "?"} as keeper? The shot goes back to candidate. The photo stays.
                        </span>
                        <div className="wf-row-6">
                          <button type="button" className="wf-btn wf-btn-pri wf-btn-s" onClick={() => void revoke(s)}>
                            Revoke
                          </button>
                          <button type="button" className="wf-btn wf-btn-s" onClick={() => setAsking(null)}>
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <aside className="wf-aside" aria-labelledby="export-h">
        <h2 className="wf-title" id="export-h">
          Export
        </h2>
        <ul className="wf-stack-8" aria-label="Files written">
          {EXPORT_FORMATS.map((f) => (
            <li key={f.label} className="wf-export-item">
              <span className="wf-checkmark" aria-hidden="true">✓</span>
              <span className="wf-stack-2">
                <span className="wf-strong">{f.label}</span>
                <span className="wf-t3 wf-xs">{f.desc}</span>
              </span>
            </li>
          ))}
        </ul>
        <div className="wf-stack-6 wf-small wf-t2">
          <span className="wf-eyebrow">INCLUDES</span>
          <span>Every shot, with keepers, verdicts and timing. All formats are written each time.</span>
          <span className="wf-mono wf-xs wf-break">{state.session.output_folder}/exports</span>
        </div>
        {unresolved > 0 && (
          <div className="wf-note-unc">
            <span className="wf-mono" aria-hidden="true">!</span>
            <span>
              {unresolved} {unresolved === 1 ? "shot has" : "shots have"} no keeper. {unresolved === 1 ? "It'll" : "They'll"} be listed as missing in
              the export.
            </span>
          </div>
        )}
        {exported && (
          <div role="status" className="wf-stack-6">
            <span className="wf-eyebrow">WRITTEN</span>
            <ul className="wf-stack-4 wf-small">
              {Object.entries(exported).map(([k, v]) => (
                <li key={k} className="wf-written">
                  <span className="wf-ok wf-mono" aria-hidden="true">✓</span>
                  <span className="wf-strong">{exportLabel(k)}</span>
                  <code className="wf-mono wf-xs wf-t2 wf-break" title={String(v)}>
                    {fileName(String(v))}
                  </code>
                </li>
              ))}
            </ul>
          </div>
        )}
        <button type="button" className="wf-btn wf-btn-pri wf-btn-l wf-push-down" disabled={exporting} onClick={() => void doExport()}>
          {exporting ? "Exporting…" : "Export files"}
        </button>
      </aside>
    </div>
  );
}
