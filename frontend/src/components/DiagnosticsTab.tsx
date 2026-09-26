import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Diagnostics, MockFailMode } from "../api/types";
import { useApp, useCoachEvents } from "../AppContext";
import { ms } from "../lib/format";
import { Chip } from "./Chip";

const FAIL_MODES: MockFailMode[] = ["none", "invalid_once", "invalid_always", "unavailable", "slow"];

export function DiagnosticsTab() {
  const { sid, state, run } = useApp();
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [learned, setLearned] = useState<string | null>(null);
  const [learning, setLearning] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await api.diagnostics(sid);
      setDiag(d);
      setLoadError(null);
      if (d.keys.learned) setLearned(d.keys.learned);
    } catch (e) {
      setLoadError((e as Error).message);
    }
  }, [sid]);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 2000);
    return () => clearInterval(t);
  }, [load]);

  useCoachEvents((ev) => {
    if (ev.type === "keys.learned") {
      setLearned((ev.payload.key as string | null) ?? null);
      setLearning(false);
    }
  });

  const provider = state?.session.assess_provider ?? (diag?.config.assess_provider as string | undefined);

  return (
    <div className="diagnostics-tab">
      {loadError && (
        <p className="alert alert-error" role="alert">
          Could not load diagnostics: {loadError}
        </p>
      )}
      {!diag ? (
        <p role="status">Loading diagnostics…</p>
      ) : (
        <>
          <section className="panel" aria-labelledby="checks-h">
            <h2 id="checks-h">Doctor checks</h2>
            <div className="table-wrap">
              <table className="compact-table">
                <thead>
                  <tr>
                    <th scope="col">Check</th>
                    <th scope="col">Status</th>
                    <th scope="col">Detail</th>
                    <th scope="col">Fix</th>
                  </tr>
                </thead>
                <tbody>
                  {diag.checks.map((c) => (
                    <tr key={c.name}>
                      <th scope="row">{c.name}</th>
                      <td>
                        <Chip value={c.status} kind={`st-${c.status}`} />
                      </td>
                      <td>{c.detail}</td>
                      <td>{c.fix}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel" aria-labelledby="providers-h">
            <h2 id="providers-h">AI providers &amp; speech</h2>
            <ul>
              {Object.entries(diag.providers.configured).map(([p, ok]) => {
                const h = diag.providers.health[p];
                return (
                  <li key={p}>
                    <strong>{p}</strong>: {ok ? "configured" : "not configured"}
                    {h && (h.ok ? ` · last call OK (${new Date(h.at).toLocaleTimeString()})` : ` · UNAVAILABLE: ${h.error ?? ""}`)}
                    {p === provider && " · used by this session"}
                  </li>
                );
              })}
            </ul>
            <p>
              Speech backend: <strong>{diag.speech_backend}</strong> · stop latency: n={diag.speech_stop_latency_ms.n}, max{" "}
              {ms(diag.speech_stop_latency_ms.max)}
              {diag.speech_stop_latency_ms.last.length > 0 && `, last ${diag.speech_stop_latency_ms.last.map((x) => Math.round(x)).join(", ")} ms`}
            </p>
            <p>
              Voice: <strong>{diag.voice.state}</strong> · Watching session: {diag.watching ?? "none"}
            </p>
          </section>

          <section className="panel" aria-labelledby="keys-h">
            <h2 id="keys-h">Global keys (Bluetooth remote)</h2>
            <dl className="kv">
              <dt>Listener</dt>
              <dd>{diag.keys.running ? "running" : "not running"}</dd>
              {diag.keys.error && (
                <>
                  <dt>Error</dt>
                  <dd className="error-text">{diag.keys.error}</dd>
                </>
              )}
              {diag.keys.ptt_key && (
                <>
                  <dt>PTT key</dt>
                  <dd>
                    {diag.keys.ptt_key} ({diag.keys.mode} mode)
                  </dd>
                  <dt>Held now</dt>
                  <dd>{diag.keys.held ? "yes" : "no"}</dd>
                </>
              )}
            </dl>
            <button
              type="button"
              disabled={!diag.keys.running}
              onClick={async () => {
                const r = await run("Learn key", () => api.learnKey());
                if (r) {
                  setLearning(true);
                  setLearned(null);
                }
              }}
            >
              Learn key
            </button>
            <p role="status" className="small">
              {learning || diag.keys.learn_waiting
                ? "Press the remote's button now…"
                : learned
                  ? `Learned key: ${learned} (set APERTURE_ALLY_PTT_KEY to use it)`
                  : ""}
            </p>
            {diag.keys.events && diag.keys.events.length > 0 && (
              <details>
                <summary>Key events ({diag.keys.events.length})</summary>
                <table className="compact-table">
                  <thead>
                    <tr>
                      <th scope="col">Kind</th>
                      <th scope="col">Key</th>
                      <th scope="col">Hold</th>
                    </tr>
                  </thead>
                  <tbody>
                    {diag.keys.events.slice(-30).map((e, i) => (
                      <tr key={i}>
                        <td>{e.kind}</td>
                        <td>{e.key}</td>
                        <td>{e.hold_ms != null ? `${e.hold_ms} ms` : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
          </section>

          <section className="panel" aria-labelledby="timing-h">
            <h2 id="timing-h">Timing ({diag.timing.n_captures} photos{sid ? ", this session" : ""})</h2>
            <div className="table-wrap">
              <table className="compact-table">
                <thead>
                  <tr>
                    <th scope="col">Interval</th>
                    <th scope="col">n</th>
                    <th scope="col">p50</th>
                    <th scope="col">p95</th>
                    <th scope="col">max</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(diag.timing.summary).map(([k, v]) => (
                    <tr key={k}>
                      <th scope="row">{k}</th>
                      <td>{v.n}</td>
                      <td>{ms(v.p50_ms)}</td>
                      <td>{ms(v.p95_ms)}</td>
                      <td>{ms(v.max_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="small muted">
              Note: speech_process_started is when the speech process was launched, not when sound became audible.
            </p>
          </section>

          {(provider === "mock" || diag.config.transcriber === "mock") && (
            <MockControls showProvider={provider === "mock"} showTranscript={diag.config.transcriber === "mock"} />
          )}

          <section className="panel" aria-labelledby="config-h">
            <details>
              <summary>
                <h2 id="config-h" className="inline-h">
                  Configuration (public, no secrets)
                </h2>
              </summary>
              <dl className="kv config">
                {Object.entries(diag.config).map(([k, v]) => (
                  <div key={k} className="kv-row">
                    <dt>{k}</dt>
                    <dd>
                      <code>{typeof v === "string" ? v : JSON.stringify(v)}</code>
                    </dd>
                  </div>
                ))}
              </dl>
            </details>
          </section>

          <section className="panel" aria-labelledby="events-h">
            <details>
              <summary>
                <h2 id="events-h" className="inline-h">
                  Recent events ({diag.recent_events.length})
                </h2>
              </summary>
              <pre className="log">
                {diag.recent_events
                  .slice()
                  .reverse()
                  .map((e) => `${e.seq} ${e.ts} ${e.type} ${JSON.stringify(e.payload)}`)
                  .join("\n")}
              </pre>
            </details>
          </section>
        </>
      )}
    </div>
  );
}

function MockControls({ showProvider, showTranscript }: { showProvider: boolean; showTranscript: boolean }) {
  const { run } = useApp();
  const [failMode, setFailMode] = useState<MockFailMode>("none");
  const [latency, setLatency] = useState("");
  const [providerMsg, setProviderMsg] = useState<string | null>(null);
  const [transcript, setTranscript] = useState("");
  const [transcriptMsg, setTranscriptMsg] = useState<string | null>(null);
  return (
    <section className="panel" aria-labelledby="mock-h">
      <h2 id="mock-h">Mock controls (testing only)</h2>
      {showProvider && (
      <form
        className="inline-form"
        onSubmit={async (e) => {
          e.preventDefault();
          const lat = latency.trim() === "" ? null : Number(latency);
          const r = await run("Set mock provider", () => api.mockProvider(failMode, lat != null && !Number.isNaN(lat) ? lat : null));
          if (r) setProviderMsg(`Mock provider: fail_mode=${r.fail_mode}, latency ${r.latency_s}s`);
        }}
      >
        <label>
          Mock provider failure mode
          <select value={failMode} onChange={(e) => setFailMode(e.target.value as MockFailMode)}>
            {FAIL_MODES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
        <label>
          Latency (s)
          <input type="number" min={0} step={0.1} value={latency} onChange={(e) => setLatency(e.target.value)} />
        </label>
        <button type="submit">Apply</button>
      </form>
      )}
      {providerMsg && <p role="status">{providerMsg}</p>}
      {showTranscript && (
      <form
        className="inline-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!transcript.trim()) return;
          const r = await run("Queue mock transcript", () => api.mockTranscript(transcript.trim()));
          if (r) {
            setTranscriptMsg(`Queued (${r.queued} waiting). Now hold the talk button.`);
            setTranscript("");
          }
        }}
      >
        <label className="grow">
          Mock transcript for the next voice question
          <input value={transcript} onChange={(e) => setTranscript(e.target.value)} />
        </label>
        <button type="submit">Queue transcript</button>
      </form>
      )}
      {transcriptMsg && <p role="status">{transcriptMsg}</p>}
    </section>
  );
}
