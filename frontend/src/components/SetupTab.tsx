import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { SetupRevisionSummary } from "../api/types";
import { useApp } from "../AppContext";
import { SetupForm } from "./SetupEditor";
import "./workflows.css";
import { revisionPhotos, setupChanges } from "./workflowsLogic";

function hhmm(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function SetupTab() {
  const { sid, state } = useApp();
  const setup = state?.setup ?? null;
  if (!state || !sid) return null;
  return (
    <div className="wf-screen wf-split wf-split-aside-320">
      <div className="wf-main">
        <div className="wf-stack-4">
          <h2 className="wf-h1">Setup</h2>
          <span className="wf-t2 wf-small">The coach only suggests changes your setup allows. Edit any time — it versions itself.</span>
        </div>
        {setup ? <SetupForm key={setup.id} setup={setup} /> : <p className="wf-t2">This session has no setup yet.</p>}
      </div>
      <SetupVersions
        sid={sid}
        currentId={setup?.id ?? null}
        currentRevision={setup?.revision ?? null}
        reloadKey={`${setup?.id}:${state.captures.length}`}
      />
    </div>
  );
}

export function SetupVersions({
  sid,
  currentId,
  currentRevision,
  reloadKey,
}: {
  sid: string;
  currentId: string | null;
  currentRevision: number | null;
  /** Changes when the list may be stale (new revision, new photos). */
  reloadKey?: string;
}) {
  const [revs, setRevs] = useState<SetupRevisionSummary[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  const load = useCallback(async () => {
    try {
      setRevs(await api.setupRevisions(sid));
      setUnavailable(false);
    } catch {
      // Older backends have no revisions endpoint; show the current version only.
      setUnavailable(true);
    }
  }, [sid]);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  const ordered = revs ? [...revs].sort((a, b) => a.revision - b.revision) : [];
  return (
    <aside className="wf-aside" aria-labelledby="versions-h">
      <h2 className="wf-eyebrow" id="versions-h">
        VERSIONS
      </h2>
      {unavailable || !revs ? (
        currentRevision != null && (
          <div className="wf-version is-current">
            <span className="wf-strong">v{currentRevision} · current</span>
            <span className="wf-t3 wf-xs">{unavailable ? "Version history isn't available from this server." : "Loading…"}</span>
          </div>
        )
      ) : (
        <ol className="wf-stack-12" reversed>
          {ordered
            .map((r, i) => ({ r, prev: i > 0 ? ordered[i - 1] : null }))
            .reverse()
            .map(({ r, prev }) => {
              const current = r.id === currentId;
              return (
                <li key={r.id} className={current ? "wf-version is-current" : "wf-version"}>
                  <div className="wf-row-between">
                    <span className={current ? "wf-strong" : undefined}>
                      v{r.revision}
                      {current && " · current"}
                    </span>
                    <span className="wf-t3 wf-xs">{hhmm(r.created_at)}</span>
                  </div>
                  <span className={current ? "wf-t2 wf-xs" : "wf-t3 wf-xs"}>
                    {setupChanges(prev, r)} · {revisionPhotos(r)}
                  </span>
                </li>
              );
            })}
        </ol>
      )}
    </aside>
  );
}
