import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { ProviderName, Session, UiTheme } from "../api/types";
import { useApp } from "../AppContext";
import { useProjects } from "./Library";
import "./library.css";
import "./newshoot.css";
import { watchFolderNote } from "./workflowsLogic";

/** New shoot (⌘N): one page, five numbered steps, and a preview of exactly what the coach will follow. */

export interface NewShootPreset {
  projectId?: string;
  templateId?: string;
}

const WATCH_KEY = "aperture-ally.last-watch-folder";
function lastWatch(): string {
  try {
    return localStorage.getItem(WATCH_KEY) ?? "";
  } catch {
    return "";
  }
}
function rememberWatch(v: string) {
  try {
    if (v) localStorage.setItem(WATCH_KEY, v);
  } catch {
    /* ignore */
  }
}

const PROVIDERS: { id: ProviderName; label: string }[] = [
  { id: "claude", label: "Claude" },
  { id: "openai", label: "OpenAI" },
  { id: "gemini", label: "Gemini" },
  { id: "mock", label: "Mock (scripted, free)" },
];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Pegasus 42 · 28 Sep" (fixed three-letter months; some locales say "Sept"). */
export function shootName(product: string, now = new Date()): string {
  return `${product.trim()} · ${now.getDate()} ${MONTHS[now.getMonth()]}`;
}

export function NewShoot({ preset, onCreated, onLibrary }: { preset: NewShootPreset | null; onCreated: (s: Session) => void; onLibrary: () => void }) {
  const { refreshSessions, theme, state } = useApp();
  const [projects] = useProjects();
  const live = (projects ?? []).filter((p) => !p.archived);
  const [projectId, setProjectId] = useState<string | null>(preset?.projectId ?? null);
  const [templateId, setTemplateId] = useState<string | null>(preset?.templateId ?? null); // "" = blank list
  const [product, setProduct] = useState("");
  const [notes, setNotes] = useState("");
  const [mine, setMine] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [watch, setWatch] = useState(lastWatch);
  const [provider, setProvider] = useState<ProviderName | "">("");
  const [teaching, setTeaching] = useState(false);
  const [simulated, setSimulated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [where, setWhere] = useState<UiTheme>(theme);
  // Outdoor previews Daylight at once, without changing the shoot that's open now; the new shoot keeps it.
  useEffect(() => {
    const root = document.documentElement;
    const prev = root.dataset.theme;
    root.dataset.theme = where === "daylight" ? "daylight" : "dark";
    return () => {
      if (prev) root.dataset.theme = prev;
    };
  }, [where]);
  useEffect(() => {
    api.prefs().then((v) => setMine(v.prefs.my_preferences ?? "")).catch(() => undefined);
  }, []);

  const project = live.find((p) => p.id === projectId) ?? live[0] ?? null;
  const templates = project?.templates ?? [];
  const chosenId = templateId ?? (templates.find((t) => t.source === "running_apparel") ?? templates[0])?.id ?? "";
  const chosen = templates.find((t) => t.id === chosenId) ?? null;
  const providers = state?.providers_configured ?? null;
  const unconfigured = (p: ProviderName) => p !== "mock" && providers != null && providers[p] === false;
  const note = watchFolderNote(watch);

  const levels = [
    { label: "Today", src: "this shoot", text: notes.trim() },
    { label: "Template", src: chosen ? `${chosen.name} v${chosen.version}` : "", text: chosen?.preferences.trim() ?? "" },
    { label: "Project", src: project?.name ?? "", text: project?.preferences.trim() ?? "" },
    { label: "Your defaults", src: "everywhere", text: mine.trim() },
  ];
  const shown = levels.filter((l) => l.text);
  const hidden = levels.filter((l) => !l.text && (l.label !== "Template" || chosen));
  const hiddenLine = hidden.length
    ? `${hidden.map((l) => `${l.label}: empty`).join(" · ")}, so ${hidden.length === 1 ? "it isn’t" : "they aren’t"} sent.`
    : "";

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!product.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const s = await api.createSession({
        name: shootName(product),
        product: product.trim(),
        watch_folder: watch.trim() || null,
        assess_provider: provider || null,
        ...(chosen ? { template_id: chosen.id } : { template: "empty" as const }),
        project_id: project?.id ?? null,
        shoot_preferences: notes.trim(),
        teaching_mode: teaching,
        simulated,
        ui_theme: where,
      });
      rememberWatch(watch.trim());
      await refreshSessions();
      onCreated(s);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  // ⌘↵ starts from anywhere on the page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        void submit();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="ns-screen">
      <form className="ns-main" onSubmit={submit} aria-labelledby="ns-h">
        <div className="lib-row-baseline ns-title-row">
          <h2 className="ns-h1" id="ns-h">
            New shoot
          </h2>
          <span className="lib-t3 lib-small">⌘N from anywhere · Tab moves between steps · ⌘↵ starts</span>
        </div>
        <div className="ns-steps">
          <span className="ns-n">1</span>
          <fieldset className="ns-step">
            <legend className="ns-legend">Project</legend>
            <div className="ns-row">
              {live.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="ns-pick ns-pick-project"
                  aria-pressed={p.id === project?.id}
                  onClick={() => {
                    setProjectId(p.id);
                    setTemplateId(null);
                  }}
                >
                  <span className="ns-pick-name">{p.name}</span>
                  <span className="lib-t3 lib-xs">
                    {p.templates.length ? `${p.templates.length} ${p.templates.length === 1 ? "template" : "templates"}` : "No templates yet"}
                    {p.preferences ? ` · ${p.preferences.split(/[.;,]/)[0].toLowerCase()}` : ""}
                  </span>
                </button>
              ))}
              {projects != null && !live.length && <span className="lib-t3 lib-small">No projects yet. The shoot starts without one.</span>}
            </div>
          </fieldset>

          <span className="ns-n">2</span>
          <fieldset className="ns-step">
            <legend className="ns-legend">Template</legend>
            {project && !templates.length ? (
              <div className="lib-empty">
                <span className="lib-strong lib-body">{project.name} has no templates yet</span>
                <span className="lib-small lib-t2">Start with a blank shot list and save it as a template at the end, or set one up in Library first.</span>
                <div className="lib-row-8">
                  <button type="button" className="lib-btn lib-btn-s" aria-pressed={chosenId === ""} onClick={() => setTemplateId("")}>
                    Blank shot list
                  </button>
                  <button type="button" className="lib-btn-text lib-small" onClick={onLibrary}>
                    Open Library ⌘6
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="ns-grid-4">
                  {templates.map((t) => (
                    <button key={t.id} type="button" className="ns-pick" aria-pressed={t.id === chosenId} onClick={() => setTemplateId(t.id)}>
                      <span className="ns-pick-name ns-pick-name-s">{t.name}</span>
                      <span className="lib-mono lib-t3 lib-xxs">
                        {t.shot_count} shots · v{t.version}
                      </span>
                    </button>
                  ))}
                  <button type="button" className="ns-pick" aria-pressed={chosenId === ""} onClick={() => setTemplateId("")}>
                    <span className="ns-pick-name ns-pick-name-s">Blank</span>
                    <span className="lib-t3 lib-xxs">Add shots as you go</span>
                  </button>
                </div>
                {chosen && (
                  <div className="ns-shots" aria-label="Shots in this template">
                    <span className="lib-eyebrow">SHOTS</span>
                    {chosen.shot_titles.map((n, i) => (
                      <span key={i} className="ns-shot-chip">
                        <span className="lib-mono lib-t3">{i + 1}</span> {n}
                      </span>
                    ))}
                  </div>
                )}
              </>
            )}
          </fieldset>

          <span className="ns-n">3</span>
          <label className="ns-step ns-maxw-520">
            <span className="ns-legend">Product</span>
            <input className="lib-input lib-input-l" required value={product} placeholder="e.g. Pegasus 42" onChange={(e) => setProduct(e.target.value)} />
            <span className="lib-t3 lib-xs">
              Shoot name: <span className="lib-t2">{product.trim() ? shootName(product) : "—"}</span> ·{" "}
              {watch.trim() ? (
                <>
                  folder <span className="lib-mono">{watch.trim()}</span>
                </>
              ) : (
                "photos go to the app’s own incoming folder (Change… to watch OM Capture’s)"
              )}
            </span>
          </label>

          <span className="ns-n">4</span>
          <fieldset className="ns-step">
            <legend className="ns-legend">Where</legend>
            <div className="ns-seg" role="radiogroup" aria-label="Where">
              {(
                [
                  ["studio", "Indoor", "Studio theme"],
                  ["daylight", "Outdoor", "Starts in Daylight theme ☀"],
                ] as const
              ).map(([id, label, sub]) => (
                <button key={id} type="button" role="radio" aria-checked={where === id} className="ns-seg-btn" onClick={() => setWhere(id)}>
                  <span className="lib-strong">{label}</span>
                  <span className="ns-seg-sub">{sub}</span>
                </button>
              ))}
            </div>
          </fieldset>

          <span className="ns-n">5</span>
          <label className="ns-step ns-maxw-640">
            <span className="lib-row-between">
              <span className="ns-legend">
                Today's notes <span className="lib-t3 lib-small ns-normal">optional</span>
              </span>
              <span className="lib-t3 lib-xs">Only this shoot · overrides everything above</span>
            </span>
            <textarea className="lib-textarea ns-notes" value={notes} maxLength={2000} placeholder="Light, place, anything different today" onChange={(e) => setNotes(e.target.value)} />
          </label>
        </div>

        {advanced && (
          <div className="ns-advanced" aria-label="Coach and folder">
            <div className="lib-field">
              <label className="lib-label" htmlFor="ns-watch">
                Watch folder
              </label>
              <input id="ns-watch" className="lib-input lib-mono" value={watch} placeholder="~/Pictures/OM Capture" aria-describedby="ns-watch-note" onChange={(e) => setWatch(e.target.value)} />
              <span id="ns-watch-note" className={note.tone === "ok" ? "lib-xs lib-ok" : "lib-xs lib-unc"}>
                {note.text}
              </span>
            </div>
            <div className="lib-field">
              <label className="lib-label" htmlFor="ns-coach">
                Coach
              </label>
              <select id="ns-coach" className="lib-input" value={provider} onChange={(e) => setProvider(e.target.value as ProviderName | "")}>
                <option value="">Server default</option>
                {PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id} disabled={unconfigured(p.id)}>
                    {p.label}
                    {unconfigured(p.id) ? " · not configured" : ""}
                  </option>
                ))}
              </select>
            </div>
            <label className="ns-check">
              <input type="checkbox" checked={teaching} onChange={(e) => setTeaching(e.target.checked)} />
              <span>Quiz me: now and then the coach asks me to predict the effect of a change</span>
            </label>
            <label className="ns-check">
              <input type="checkbox" checked={simulated} onChange={(e) => setSimulated(e.target.checked)} />
              <span>
                Simulated practice run <span className="lib-t3">(marked SIMULATED; not hardware evidence)</span>
              </span>
            </label>
            {provider === "mock" && <div className="ns-mock">MOCK PROVIDER · verdicts will be scripted. Labelled on every screen.</div>}
          </div>
        )}

        {error && (
          <div role="alert" className="lib-error ns-indent">
            <span className="lib-glyph lib-ret">✕</span>
            <span className="lib-grow">Couldn't start the shoot: {error}. Nothing was started.</span>
            <button type="button" className="lib-btn lib-btn-s" onClick={() => setAdvanced(true)}>
              Choose folder…
            </button>
          </div>
        )}
        <div className="ns-foot">
          <span className="lib-small lib-t2">
            Coach: {PROVIDERS.find((p) => p.id === provider)?.label ?? "server default"} · Quiz {teaching ? "on" : "off"}
            {watch.trim() ? ` · ${watch.trim()}` : ""}
            <button type="button" className="lib-btn-text lib-small ns-change" aria-expanded={advanced} onClick={() => setAdvanced((a) => !a)}>
              Change…
            </button>
          </span>
          <button type="submit" className="lib-btn lib-btn-pri ns-start" disabled={busy || !product.trim()}>
            {busy ? "Starting…" : where === "daylight" ? "Start outdoor shoot" : "Start shoot"} <span className="lib-kbd">⌘↵</span>
          </button>
        </div>
      </form>

      <aside className="ns-aside" aria-label="What the coach will follow">
        <div className="lib-stack-2">
          <span className="lib-eyebrow">WHAT THE COACH WILL FOLLOW</span>
          <span className="lib-small lib-t2">Most specific first. When two disagree, the higher one wins.</span>
        </div>
        <div data-testid="coach-follows">
          {shown.map((l) => (
            <div key={l.label} className="ns-level">
              <span className="lib-row-between">
                <span className="lib-xs lib-bold">{l.label}</span>
                <span className="lib-xs lib-t3">{l.src}</span>
              </span>
              <span className="ns-level-text">{l.text}</span>
            </div>
          ))}
        </div>
        {hiddenLine && <span className="lib-xs lib-t3 ns-hidden">{hiddenLine}</span>}
        <div className="ns-aside-foot">
          <span className="lib-eyebrow">SHOT LIST</span>
          <span className="lib-body">{chosen ? `${chosen.shot_count} shots from ${chosen.name} v${chosen.version}` : "Blank · add shots as you go"}</span>
          <span className="lib-xs lib-t3">The shoot gets its own copy. Changes stay in the shoot until you save them back to the template.</span>
        </div>
      </aside>
    </div>
  );
}
