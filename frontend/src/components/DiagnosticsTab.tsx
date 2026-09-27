import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Diagnostics, MockFailMode } from "../api/types";
import { useApp, useCoachEvents } from "../AppContext";
import "./workflows.css";
import { REPLAYS, TIMING_LABELS, healthRows, seconds, type HealthRow } from "./workflowsLogic";

const FAIL_MODES: MockFailMode[] = ["none", "invalid_once", "invalid_always", "unavailable", "slow"];

const HEALTH_META = (ok: boolean | null) =>
  ok === true
    ? { glyph: "✓", word: "OK", cls: "is-ok" }
    : ok === false
      ? { glyph: "✕", word: "Problem", cls: "is-ret" }
      : { glyph: "!", word: "Check", cls: "is-unc" };

export function DiagnosticsTab() {
  const { sid, state } = useApp();
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      const d = await api.diagnostics(sid);
      setDiag(d);
      setLoadError(null);
    } catch (e) {
      setLoadError((e as Error).message);
    }
    setNow(Date.now());
  }, [sid]);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 2000);
    return () => clearInterval(t);
  }, [load]);

  const provider = state?.session.assess_provider ?? (diag?.config.assess_provider as string | undefined);
  const rows = healthRows(diag, state, now);

  return (
    <div className="wf-screen wf-diag">
      {loadError && (
        <p className="wf-note-ret wf-span-2" role="alert">
          Could not load diagnostics: {loadError}
        </p>
      )}
      <div className="wf-stack-12">
        <h2 className="wf-title" id="health-h">
          Health
        </h2>
        <HealthList rows={rows} />
        {diag && (
          <details className="wf-details">
            <summary>All checks ({diag.checks.length})</summary>
            <table className="wf-table">
              <thead>
                <tr>
                  <th scope="col">Check</th>
                  <th scope="col">Status</th>
                  <th scope="col">Detail</th>
                  <th scope="col">Fix</th>
                </tr>
              </thead>
              <tbody>
                {diag.checks.map((c) => {
                  const m = HEALTH_META(c.status === "ok" ? true : c.status === "fail" ? false : null);
                  return (
                    <tr key={c.name}>
                      <th scope="row">{c.name}</th>
                      <td className={`wf-health-word ${m.cls}`}>
                        <span className="wf-mono" aria-hidden="true">{m.glyph}</span> {m.word}
                      </td>
                      <td className="wf-break">{c.detail}</td>
                      <td>{c.fix}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </details>
        )}

        <h2 className="wf-title wf-mt-12">
          Timings{" "}
          <span className="wf-t3 wf-small wf-normal">
            {diag ? `${diag.timing.n_captures} photos${sid ? " · this session" : ""}` : ""}
          </span>
        </h2>
        {diag && Object.keys(diag.timing.summary).length > 0 ? (
          <table className="wf-table wf-timings">
            <thead>
              <tr>
                <th scope="col">STEP</th>
                <th scope="col">N</th>
                <th scope="col">MEDIAN</th>
                <th scope="col">P95</th>
                <th scope="col">SLOWEST</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(diag.timing.summary).map(([k, v]) => (
                <tr key={k}>
                  <th scope="row" title={k}>
                    {TIMING_LABELS[k] ?? k}
                  </th>
                  <td className="wf-mono">{v.n}</td>
                  <td className="wf-mono">{seconds(v.p50_ms)}</td>
                  <td className="wf-mono">{seconds(v.p95_ms)}</td>
                  <td className="wf-mono">{seconds(v.max_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="wf-t3 wf-small">{diag ? "No timed photos yet." : "Loading…"}</p>
        )}
        <p className="wf-t3 wf-xs">“Speech process started” is when speech was launched, not when sound became audible.</p>
      </div>

      <div className="wf-stack-16">
        <h2 className="wf-title">Remote button test</h2>
        <RemoteTest diag={diag} />
        <h2 className="wf-title wf-mt-8">Replay a scenario</h2>
        <Replay sid={sid} />
      </div>

      {diag && (
        <div className="wf-span-2 wf-stack-12">
          <details className="wf-details">
            <summary>Recent events ({diag.recent_events.length})</summary>
            <ol className="wf-events">
              {diag.recent_events
                .slice(-60)
                .reverse()
                .map((e) => (
                  <li key={e.seq}>
                    <span className="wf-t3">{new Date(e.ts).toLocaleTimeString()}</span> <span className="wf-strong">{e.type}</span>{" "}
                    <span className="wf-t3 wf-break">{JSON.stringify(e.payload)}</span>
                  </li>
                ))}
            </ol>
          </details>
          <details className="wf-details">
            <summary>Developer</summary>
            <div className="wf-stack-16 wf-pad-top">
              <p className="wf-t2 wf-small">
                Voice: <strong>{diag.voice.state}</strong> · Watching session: {diag.watching ?? "none"} · Speech stop latency: n=
                {diag.speech_stop_latency_ms.n}, max {seconds(diag.speech_stop_latency_ms.max)}
              </p>
              {(provider === "mock" || diag.config.transcriber === "mock") && (
                <MockControls showProvider={provider === "mock"} showTranscript={diag.config.transcriber === "mock"} />
              )}
              <details className="wf-details">
                <summary>Configuration (public, no secrets)</summary>
                <dl className="wf-kv">
                  {Object.entries(diag.config).map(([k, v]) => (
                    <div key={k}>
                      <dt>{k}</dt>
                      <dd>
                        <code className="wf-break">{typeof v === "string" ? v : JSON.stringify(v)}</code>
                      </dd>
                    </div>
                  ))}
                </dl>
              </details>
            </div>
          </details>
        </div>
      )}
    </div>
  );
}

export function HealthList({ rows }: { rows: HealthRow[] }) {
  return (
    <ul className="wf-health" aria-labelledby="health-h">
      {rows.map((h) => {
        const m = HEALTH_META(h.ok);
        return (
          <li key={h.label.split(":")[0]} className="wf-health-row">
            <span className={`wf-health-tile ${m.cls}`}>
              <span aria-hidden="true">{m.glyph}</span>
              <span className="sr-only">{m.word}:</span>
            </span>
            <span className="wf-grow">{h.label}</span>
            <span className="wf-mono wf-t3 wf-xs wf-break wf-right">{h.detail}</span>
          </li>
        );
      })}
    </ul>
  );
}

function RemoteTest({ diag }: { diag: Diagnostics | null }) {
  const { run } = useApp();
  const [presses, setPresses] = useState(0);
  const [lastKey, setLastKey] = useState<string | null>(null);
  const [learned, setLearned] = useState<string | null>(null);
  const [learning, setLearning] = useState(false);

  useEffect(() => {
    if (diag?.keys.learned) setLearned(diag.keys.learned);
  }, [diag?.keys.learned]);
  useCoachEvents((ev) => {
    if (ev.type === "keys.learned") {
      setLearned((ev.payload.key as string | null) ?? null);
      setLearning(false);
    }
  });

  const got = presses > 0;
  const lastHold = diag?.keys.events?.slice().reverse().find((e) => e.hold_ms != null)?.hold_ms;
  return (
    <div className="wf-stack-12">
      <button
        type="button"
        className={got ? "wf-keytest is-got" : "wf-keytest"}
        onKeyDown={(e) => {
          if (e.key === "Tab") return;
          // Keep app-wide shortcuts (e.g. Space for push-to-talk) from also firing during the test.
          e.preventDefault();
          e.stopPropagation();
          setPresses((n) => n + 1);
          setLastKey(e.key === " " ? "Space" : e.key);
        }}
        onClick={(e) => {
          // Keyboard activation is already counted in onKeyDown; count mouse clicks only.
          if (e.detail > 0) {
            setPresses((n) => n + 1);
            setLastKey("click");
          }
        }}
      >
        <span className="wf-keytest-title">{got ? "✓ Got it" : "Press your button"}</span>
        <span className="wf-t2 wf-small" aria-live="polite">
          {got
            ? `Received “${lastKey}” · ${presses} press${presses > 1 ? "es" : ""}`
            : "Focus here, then press the remote (or Space)"}
        </span>
      </button>
      {diag && (
        <div className="wf-small wf-t2 wf-stack-6">
          <span>
            Global listener: {diag.keys.running ? "running" : "not running"}
            {diag.keys.ptt_key && ` · push-to-talk key ${diag.keys.ptt_key} (${diag.keys.mode} mode)`}
            {diag.keys.held && " · held now"}
            {lastHold != null && ` · last hold ${lastHold} ms`}
          </span>
          {diag.keys.error && <span className="wf-ret">{diag.keys.error}</span>}
          <div className="wf-row-8">
            <button
              type="button"
              className="wf-btn wf-btn-s"
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
            <span role="status" className="wf-center">
              {learning || diag.keys.learn_waiting
                ? "Press the remote's button now…"
                : learned
                  ? `Learned key: ${learned} (set APERTURE_ALLY_PTT_KEY to use it)`
                  : ""}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function Replay({ sid }: { sid: string | null }) {
  const { run } = useApp();
  const [scenario, setScenario] = useState<string>("basic_loop");
  const [log, setLog] = useState<string[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useCoachEvents((ev) => {
    if (!sid || ev.session_id !== sid) return;
    if (ev.type === "replay.log") setLog((l) => [...l.slice(-199), String(ev.payload.message ?? "")]);
    if (ev.type === "replay.completed") {
      setStatus("Replay completed.");
      setRunning(false);
    }
    if (ev.type === "replay.failed") {
      setStatus(`Replay failed: ${String(ev.payload.error ?? "")}`);
      setRunning(false);
    }
  });

  return (
    <form
      className="wf-stack-12"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!sid) return;
        setLog([]);
        setStatus("Replay running…");
        setRunning(true);
        const r = await run("Run replay", () => api.imports(sid, { replay: scenario }));
        if (!r) {
          setStatus(null);
          setRunning(false);
        }
      }}
    >
      <fieldset className="wf-fieldset">
        <legend className="sr-only">Replay scenario</legend>
        <div className="wf-stack-6">
          {REPLAYS.map((r) => (
            <label key={r.id} className="wf-radio-card">
              <input type="radio" name="replay" value={r.id} checked={scenario === r.id} onChange={() => setScenario(r.id)} />
              <span className="wf-stack-2">
                <span className="wf-mono">{r.id}</span>
                <span className="wf-t3 wf-xs">{r.desc}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="wf-row-12 wf-wrap">
        <button type="submit" className="wf-btn wf-btn-pri" disabled={!sid || running}>
          {running ? "Replaying…" : "Start replay"}
        </button>
        <span className="wf-row-8 wf-xs wf-t2">
          <span className="wf-tag wf-tag-mock">SIMULATED</span>Any replay marks the session SIMULATED until it ends.
        </span>
      </div>
      {!sid && <p className="wf-t3 wf-small">Open a session first; replay writes into its watch folder.</p>}
      <p className="wf-t3 wf-xs">
        Replay writes fixture photos into the open session's watch folder like a tethered camera would. It switches shots, sets
        regions and accepts keepers itself.
      </p>
      {status && (
        <p role="status" data-testid="replay-status">
          {status}
        </p>
      )}
      {log.length > 0 && (
        <details className="wf-details">
          <summary>Replay log ({log.length} lines)</summary>
          <pre className="wf-log">{log.join("\n")}</pre>
        </details>
      )}
    </form>
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
    <section className="wf-stack-12" aria-labelledby="mock-h">
      <h3 id="mock-h" className="wf-strong">
        Mock controls (testing only)
      </h3>
      {showProvider && (
        <form
          className="wf-row-8 wf-wrap wf-end"
          onSubmit={async (e) => {
            e.preventDefault();
            const lat = latency.trim() === "" ? null : Number(latency);
            const r = await run("Set mock provider", () => api.mockProvider(failMode, lat != null && !Number.isNaN(lat) ? lat : null));
            if (r) setProviderMsg(`Mock provider: fail_mode=${r.fail_mode}, latency ${r.latency_s}s`);
          }}
        >
          <label className="wf-field">
            <span className="wf-label">Mock provider failure mode</span>
            <select className="wf-input" value={failMode} onChange={(e) => setFailMode(e.target.value as MockFailMode)}>
              {FAIL_MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="wf-field">
            <span className="wf-label">Latency (s)</span>
            <input className="wf-input" type="number" min={0} step={0.1} value={latency} onChange={(e) => setLatency(e.target.value)} />
          </label>
          <button type="submit" className="wf-btn">
            Apply
          </button>
        </form>
      )}
      {providerMsg && <p role="status">{providerMsg}</p>}
      {showTranscript && (
        <form
          className="wf-row-8 wf-wrap wf-end"
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
          <label className="wf-field wf-grow">
            <span className="wf-label">Mock transcript for the next voice question</span>
            <input className="wf-input" value={transcript} onChange={(e) => setTranscript(e.target.value)} />
          </label>
          <button type="submit" className="wf-btn">
            Queue transcript
          </button>
        </form>
      )}
      {transcriptMsg && <p role="status">{transcriptMsg}</p>}
    </section>
  );
}
