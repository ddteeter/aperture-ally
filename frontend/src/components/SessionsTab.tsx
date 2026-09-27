import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { ProviderName, Session, TemplateName, UiTheme } from "../api/types";
import { useApp } from "../AppContext";
import "./workflows.css";
import { TEMPLATE_SHOTS, watchFolderNote } from "./workflowsLogic";

/** Fields a newer backend may add to the session list; shown when present. */
type SessionRow = Session & {
  template?: string | null;
  capture_count?: number;
  keeper_count?: number;
  shot_count?: number;
};

const TEMPLATE_LABEL: Record<string, string> = {
  running_apparel: "Apparel detail",
  running_shoe: "Shoe product",
  empty: "Blank",
};

const TEMPLATES: { id: TemplateName; label: string }[] = [
  { id: "running_apparel", label: "Apparel detail" },
  { id: "running_shoe", label: "Shoe product" },
  { id: "empty", label: "Blank" },
];

const PROVIDERS: { id: ProviderName; label: string; desc: string }[] = [
  { id: "claude", label: "Claude", desc: "Cloud · paid" },
  { id: "openai", label: "OpenAI", desc: "Cloud · paid" },
  { id: "gemini", label: "Gemini", desc: "Cloud · paid" },
  { id: "mock", label: "Mock", desc: "Scripted · free" },
];

const PROVIDER_LABEL: Record<string, string> = { claude: "Claude", openai: "OpenAI", gemini: "Gemini", mock: "MOCK PROVIDER" };

const STATUS: Record<string, { glyph: string; word: string }> = {
  active: { glyph: "●", word: "Active" },
  paused: { glyph: "‖", word: "Paused" },
  completed: { glyph: "✓", word: "Completed" },
};

function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (d.toDateString() === new Date().toDateString()) return "Today";
  return d.toLocaleDateString([], { month: "short", day: "2-digit" });
}

export function SessionsTab({ sessions, onOpen }: { sessions: Session[]; onOpen: (sid: string) => void }) {
  const { sid, state, run, refresh, refreshSessions } = useApp();
  const rows = [...sessions].reverse() as SessionRow[];

  const photos = (s: SessionRow) => (s.id === sid && state ? state.captures.length : s.capture_count);
  const keepers = (s: SessionRow) =>
    s.id === sid && state
      ? `${state.coverage.resolved} / ${state.coverage.total}`
      : s.keeper_count != null && s.shot_count != null
        ? `${s.keeper_count} / ${s.shot_count}`
        : null;

  return (
    <div className="wf-screen wf-split wf-split-aside-520">
      <div className="wf-main">
        <div className="wf-row-baseline wf-gap-14">
          <h2 className="wf-h1" id="sessions-h">
            Sessions
          </h2>
          <span className="wf-t3 wf-small">
            {sessions.length} {sessions.length === 1 ? "shoot" : "shoots"} · stored on this computer
          </span>
        </div>
        {rows.length === 0 ? (
          <p className="wf-t2">No sessions yet. Create one on the right.</p>
        ) : (
          <div className="wf-sess-table" role="table" aria-labelledby="sessions-h">
            <div className="wf-sess-row wf-sess-headrow" role="row">
              <span role="columnheader">SHOOT</span>
              <span role="columnheader">DATE</span>
              <span role="columnheader">PHOTOS</span>
              <span role="columnheader">KEEPERS</span>
              <span role="columnheader">PROVIDER</span>
              <span role="columnheader">STATUS</span>
            </div>
            {rows.map((s) => {
              const st = STATUS[s.status] ?? { glyph: "·", word: s.status };
              const k = keepers(s);
              const p = photos(s);
              const tpl = s.template ? TEMPLATE_LABEL[s.template] ?? s.template : null;
              return (
                <div key={s.id} role="row" className={s.id === sid ? "wf-sess-row is-current" : "wf-sess-row"}>
                  <span role="cell" className="wf-stack-2 wf-minw0">
                    <button type="button" className="wf-sess-open" onClick={() => onOpen(s.id)}>
                      {s.name}
                      <span className="sr-only"> — open</span>
                    </button>
                    <span className="wf-t3 wf-xs">
                      {[s.product || "—", tpl].filter(Boolean).join(" · ")}
                      {s.id === sid && " · open now"}
                    </span>
                  </span>
                  <span role="cell" className="wf-t2 wf-small">
                    {shortDate(s.created_at)}
                  </span>
                  <span role="cell" className="wf-mono wf-small">
                    {p ?? "—"}
                  </span>
                  <span role="cell" className="wf-mono wf-small">
                    {k ?? "—"}
                  </span>
                  <span role="cell" className="wf-tags">
                    <span className={s.assess_provider === "mock" ? "wf-tag wf-tag-mock" : "wf-tag"}>
                      {PROVIDER_LABEL[s.assess_provider] ?? s.assess_provider}
                    </span>
                    {s.simulated && <span className="wf-tag wf-tag-mock">SIMULATED</span>}
                  </span>
                  <span role="cell" className="wf-sess-status wf-small">
                    <span>
                      <span className="wf-mono" aria-hidden="true">{st.glyph}</span> {st.word}
                    </span>
                    {s.status !== "active" && (
                      <button
                        type="button"
                        className="wf-btn-text wf-xs"
                        onClick={() =>
                          run("Make active", async () => {
                            await api.patchSession(s.id, { status: "active" });
                            await refreshSessions();
                            if (s.id === sid) await refresh();
                          })
                        }
                      >
                        Make active<span className="sr-only"> {s.name}</span>
                      </button>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        )}
        <p className="wf-t3 wf-xs">Only the active session's watch folder is watched; creating or activating a session pauses the others.</p>
        {state && sid && <ImportPhotos sid={sid} />}
      </div>

      <CreateSession onCreated={(s) => onOpen(s.id)} providers={state?.providers_configured ?? null} />
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
  const { run, refreshSessions, theme } = useApp();
  const [name, setName] = useState("");
  const [product, setProduct] = useState("");
  const [watch, setWatch] = useState("");
  const [provider, setProvider] = useState<ProviderName | "">("");
  const [template, setTemplate] = useState<TemplateName>("running_apparel");
  const [teaching, setTeaching] = useState(true);
  const [simulated, setSimulated] = useState(false);
  const [uiTheme, setUiTheme] = useState<UiTheme>(theme);
  const [busy, setBusy] = useState(false);
  const note = watchFolderNote(watch);
  const unconfigured = (p: ProviderName) => p !== "mock" && providers != null && providers[p] === false;

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
        ui_theme: uiTheme,
      }),
    );
    setBusy(false);
    if (s) {
      setName("");
      await refreshSessions();
      onCreated(s);
    }
  };

  return (
    <aside className="wf-aside wf-aside-wide" aria-labelledby="create-h">
      <form onSubmit={submit} className="wf-stack-18">
        <h2 className="wf-title-l" id="create-h">
          New shoot
        </h2>
        <label className="wf-field">
          <span className="wf-label">Name</span>
          <input className="wf-input" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="wf-field">
          <span className="wf-label">Product</span>
          <input className="wf-input" value={product} onChange={(e) => setProduct(e.target.value)} placeholder="e.g. Ridgeline 2.5L running shell" />
        </label>

        <fieldset className="wf-fieldset">
          <legend className="wf-label">Template</legend>
          <div className="wf-cards wf-cards-3">
            {TEMPLATES.map((t) => (
              <label key={t.id} className="wf-pick">
                <input type="radio" name="new-template" checked={template === t.id} onChange={() => setTemplate(t.id)} />
                <span className="wf-strong">{t.label}</span>
                <span className="wf-t3 wf-xxs">{TEMPLATE_SHOTS[t.id] ? `${TEMPLATE_SHOTS[t.id]} shots` : "Start empty"}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className="wf-fieldset">
          <legend className="wf-label">AI provider</legend>
          <div className="wf-cards wf-cards-4">
            {PROVIDERS.map((p) => {
              const off = unconfigured(p.id);
              return (
                <label key={p.id} className={off ? "wf-pick is-disabled" : "wf-pick"}>
                  <input
                    type="radio"
                    name="new-provider"
                    checked={provider === p.id}
                    disabled={off}
                    onChange={() => setProvider(p.id)}
                  />
                  <span className="wf-strong">{p.label}</span>
                  <span className="wf-t3 wf-xxs">{off ? "Not configured" : p.desc}</span>
                </label>
              );
            })}
          </div>
          {provider === "" && <span className="wf-t3 wf-xs">None picked: the server default is used.</span>}
          {providers && PROVIDERS.some((p) => unconfigured(p.id)) && (
            <span className="wf-t3 wf-xs">Providers without an API key are disabled. Add keys in the server's environment.</span>
          )}
          {provider === "mock" && (
            <div className="wf-mock-band">
              <span className="wf-mock-tag">MOCK PROVIDER</span>Verdicts will be scripted. Labelled on every screen.
            </div>
          )}
        </fieldset>

        <div className="wf-field">
          <label htmlFor="new-watch" className="wf-label">
            Watch folder
          </label>
          <input
            id="new-watch"
            className="wf-input wf-mono"
            value={watch}
            onChange={(e) => setWatch(e.target.value)}
            placeholder="~/Pictures/Tether/my-shoot"
            aria-describedby="watch-note"
          />
          <span id="watch-note" className={note.tone === "ok" ? "wf-xs wf-ok" : "wf-xs wf-unc"}>
            {note.text}
          </span>
        </div>

        <button
          type="button"
          role="switch"
          aria-checked={teaching}
          className="wf-toggle"
          onClick={() => setTeaching((t) => !t)}
        >
          <span className={teaching ? "wf-switch is-on" : "wf-switch"} aria-hidden="true">
            <span />
          </span>
          <span className="wf-stack-2">
            <span className="wf-strong">Teaching mode · {teaching ? "On" : "Off"}</span>
            <span className="wf-t3 wf-xs">
              {teaching ? "Coach explains why and names the concept" : "Just the action — faster to hear"}
            </span>
          </span>
        </button>

        <fieldset className="wf-fieldset">
          <legend className="wf-label">Where are you shooting?</legend>
          <div className="wf-cards wf-cards-2">
            <label className="wf-pick">
              <input type="radio" name="new-theme" checked={uiTheme === "studio"} onChange={() => setUiTheme("studio")} />
              <span className="wf-strong">Indoor</span>
              <span className="wf-t3 wf-xxs">Studio · dark screen</span>
            </label>
            <label className="wf-pick">
              <input type="radio" name="new-theme" checked={uiTheme === "daylight"} onChange={() => setUiTheme("daylight")} />
              <span className="wf-strong">Outdoor</span>
              <span className="wf-t3 wf-xxs">☀ Daylight · readable in sun</span>
            </label>
          </div>
        </fieldset>

        <label className="wf-check">
          <input type="checkbox" checked={simulated} onChange={(e) => setSimulated(e.target.checked)} />
          <span>
            Simulated practice run <span className="wf-t3">— marked SIMULATED; results are not hardware evidence</span>
          </span>
        </label>

        <button type="submit" className="wf-btn wf-btn-pri wf-btn-l" disabled={busy || !name.trim()}>
          {busy ? "Creating…" : "Create and start shooting"}
        </button>
      </form>
    </aside>
  );
}

function ImportPhotos({ sid }: { sid: string }) {
  const { state, run, refresh } = useApp();
  const [files, setFiles] = useState<File[]>([]);
  const [shotId, setShotId] = useState<string>("");
  const [autoCoach, setAutoCoach] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <details className="wf-details">
      <summary>Import photos into “{state?.session.name}”</summary>
      <form
        className="wf-stack-12"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!files.length) return;
          setMsg("Uploading…");
          const r = await run("Upload", () => api.upload(sid, files, shotId || null, autoCoach));
          setMsg(r ? `Imported ${r.capture_ids.length} photo(s).` : null);
          await refresh();
        }}
      >
        <label className="wf-field">
          <span className="wf-label">Photo files (JPEG / RAW)</span>
          <input
            type="file"
            multiple
            accept=".jpg,.jpeg,.orf,.cr2,.cr3,.nef,.arw,.raf,.rw2,.dng,image/jpeg"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          />
        </label>
        <label className="wf-field">
          <span className="wf-label">Assign to shot</span>
          <select className="wf-input" value={shotId} onChange={(e) => setShotId(e.target.value)}>
            <option value="">Active shot</option>
            {state?.shots.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </label>
        <label className="wf-check">
          <input type="checkbox" checked={autoCoach} onChange={(e) => setAutoCoach(e.target.checked)} />
          <span>Coach automatically after import</span>
        </label>
        <div>
          <button type="submit" className="wf-btn" disabled={!files.length}>
            Upload {files.length ? `${files.length} file(s)` : ""}
          </button>
        </div>
        {msg && <p role="status">{msg}</p>}
      </form>
    </details>
  );
}
