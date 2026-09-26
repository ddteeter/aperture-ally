import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { ProviderName, Session } from "../api/types";
import { useApp, useCoachEvents } from "../AppContext";
import { shortTime } from "../lib/format";

const REPLAYS = ["basic_loop", "ingest_stress", "stale_switch"] as const;

export function SessionsTab({ sessions, onOpen }: { sessions: Session[]; onOpen: (sid: string) => void }) {
  const { sid, state, run, refresh, refreshSessions } = useApp();
  return (
    <div className="sessions-tab">
      <section className="panel" aria-labelledby="sessions-h">
        <h2 id="sessions-h">Sessions</h2>
        {sessions.length === 0 ? (
          <p>No sessions yet. Create one below.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Product</th>
                  <th scope="col">Status</th>
                  <th scope="col">Simulated</th>
                  <th scope="col">Created</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {[...sessions].reverse().map((s) => (
                  <tr key={s.id} className={s.id === sid ? "row-current" : undefined}>
                    <td>
                      {s.name}
                      {s.id === sid && <span className="muted"> (open)</span>}
                    </td>
                    <td>{s.product}</td>
                    <td>{s.status}</td>
                    <td>{s.simulated ? "yes" : "no"}</td>
                    <td>{shortTime(s.created_at)}</td>
                    <td className="actions">
                      <button type="button" onClick={() => onOpen(s.id)}>
                        Open
                      </button>
                      {s.status !== "active" && (
                        <button
                          type="button"
                          onClick={() =>
                            run("Make active", async () => {
                              await api.patchSession(s.id, { status: "active" });
                              await refreshSessions();
                              if (s.id === sid) await refresh();
                            })
                          }
                        >
                          Make active
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted small">Only the active session's watch folder is watched; creating or activating a session pauses the others.</p>
      </section>

      <CreateSession onCreated={(s) => onOpen(s.id)} providers={state?.providers_configured ?? null} />

      {state && sid && <ReplayAndImport sid={sid} />}
    </div>
  );
}

function CreateSession({
  onCreated,
  providers,
}: {
  onCreated: (s: Session) => void;
  providers: Record<ProviderName, boolean> | null;
}) {
  const { run, refreshSessions } = useApp();
  const [name, setName] = useState("");
  const [product, setProduct] = useState("");
  const [watch, setWatch] = useState("");
  const [provider, setProvider] = useState<ProviderName | "">("");
  const [template, setTemplate] = useState<"running_shoe" | "empty">("running_shoe");
  const [teaching, setTeaching] = useState(true);
  const [simulated, setSimulated] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const s = await run("Create session", () =>
      api.createSession({
        name: name.trim(),
        product: product.trim(),
        watch_folder: watch.trim() || null,
        assess_provider: provider || null,
        template,
        teaching_mode: teaching,
        simulated,
      }),
    );
    setBusy(false);
    if (s) {
      setName("");
      await refreshSessions();
      onCreated(s);
    }
  };

  const configured = (p: ProviderName) =>
    providers ? (providers[p] ? " (configured)" : " (not configured)") : "";

  return (
    <section className="panel" aria-labelledby="create-h">
      <h2 id="create-h">New session</h2>
      <form onSubmit={submit} className="form-grid">
        <label>
          Name <span className="req">(required)</span>
          <input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Product
          <input value={product} onChange={(e) => setProduct(e.target.value)} placeholder="e.g. Trail shoe X" />
        </label>
        <label>
          Watch folder (optional)
          <input
            value={watch}
            onChange={(e) => setWatch(e.target.value)}
            placeholder="default: data dir/incoming/<session id>"
          />
        </label>
        <label>
          AI provider
          <select value={provider} onChange={(e) => setProvider(e.target.value as ProviderName | "")}>
            <option value="">Server default</option>
            <option value="mock">mock — heuristic stand-in{configured("mock")}</option>
            <option value="openai">openai{configured("openai")}</option>
            <option value="gemini">gemini{configured("gemini")}</option>
            <option value="claude">claude{configured("claude")}</option>
          </select>
        </label>
        <label>
          Shot list template
          <select value={template} onChange={(e) => setTemplate(e.target.value as "running_shoe" | "empty")}>
            <option value="running_shoe">Running shoe (6 shots)</option>
            <option value="empty">Empty</option>
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={teaching} onChange={(e) => setTeaching(e.target.checked)} />
          Teaching mode (occasional "explain it back" prompts)
        </label>
        <label className="check">
          <input type="checkbox" checked={simulated} onChange={(e) => setSimulated(e.target.checked)} />
          Simulated session (replay / practice — results are not hardware evidence)
        </label>
        <div>
          <button type="submit" className="primary" disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create session"}
          </button>
        </div>
      </form>
    </section>
  );
}

function ReplayAndImport({ sid }: { sid: string }) {
  const { state, run, refresh } = useApp();
  const [scenario, setScenario] = useState<string>("basic_loop");
  const [replayLog, setReplayLog] = useState<string[]>([]);
  const [replayStatus, setReplayStatus] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [shotId, setShotId] = useState<string>("");
  const [autoCoach, setAutoCoach] = useState(true);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);

  useCoachEvents((ev) => {
    if (ev.session_id !== sid) return;
    if (ev.type === "replay.log") setReplayLog((l) => [...l.slice(-199), String(ev.payload.message ?? "")]);
    if (ev.type === "replay.completed") setReplayStatus("Replay completed.");
    if (ev.type === "replay.failed") setReplayStatus(`Replay failed: ${String(ev.payload.error ?? "")}`);
  });

  return (
    <section className="panel" aria-labelledby="replay-h">
      <h2 id="replay-h">Replay &amp; import for “{state?.session.name}”</h2>
      <form
        className="inline-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setReplayLog([]);
          setReplayStatus("Replay running…");
          const r = await run("Run replay", () => api.imports(sid, { replay: scenario }));
          if (!r) setReplayStatus(null);
        }}
      >
        <label>
          Replay scenario
          <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
            {REPLAYS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Run replay scenario</button>
      </form>
      <p className="muted small">
        Replay writes fixture photos into this session's watch folder like a tethered camera would. It
        switches shots, sets regions and accepts keepers itself.
      </p>
      {replayStatus && (
        <p role="status" data-testid="replay-status">
          {replayStatus}
        </p>
      )}
      {replayLog.length > 0 && (
        <details>
          <summary>Replay log ({replayLog.length} lines)</summary>
          <pre className="log">{replayLog.join("\n")}</pre>
        </details>
      )}

      <h3>Import photos manually</h3>
      <form
        className="form-grid"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!files.length) return;
          setUploadMsg("Uploading…");
          const r = await run("Upload", () => api.upload(sid, files, shotId || null, autoCoach));
          setUploadMsg(r ? `Imported ${r.capture_ids.length} photo(s).` : null);
          await refresh();
        }}
      >
        <label>
          Photo files (JPEG / RAW)
          <input
            type="file"
            multiple
            accept=".jpg,.jpeg,.orf,.cr2,.cr3,.nef,.arw,.raf,.rw2,.dng,image/jpeg"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          />
        </label>
        <label>
          Assign to shot
          <select value={shotId} onChange={(e) => setShotId(e.target.value)}>
            <option value="">Active shot</option>
            {state?.shots.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={autoCoach} onChange={(e) => setAutoCoach(e.target.checked)} />
          Coach automatically after import
        </label>
        <div>
          <button type="submit" disabled={!files.length}>
            Upload {files.length ? `${files.length} file(s)` : ""}
          </button>
        </div>
      </form>
      {uploadMsg && <p role="status">{uploadMsg}</p>}
    </section>
  );
}
