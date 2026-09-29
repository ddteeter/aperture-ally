import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { api } from "../api/client";
import type { Criterion, Project, ShootTemplate, TemplateShot, TemplateSummary, TemplateVersion } from "../api/types";
import { useApp } from "../AppContext";
import { nextCriterionId } from "../lib/regions";
import { useProjects } from "./Library";
import "./library.css";

/** Library (⌘6): Your defaults → Project → Shoot template. Reusable definitions, edited between shoots. */

type Sel = { kind: "defaults" } | { kind: "project"; id: string } | { kind: "template"; id: string };
const SEL_KEY = "aperture-ally.library";

function loadSel(): Sel | null {
  try {
    const v = JSON.parse(localStorage.getItem(SEL_KEY) ?? "null");
    return v && typeof v.kind === "string" ? (v as Sel) : null;
  } catch {
    return null;
  }
}
function saveSel(s: Sel) {
  try {
    localStorage.setItem(SEL_KEY, JSON.stringify(s));
  } catch {
    /* ignore */
  }
}

/** "Today", "27 Sep", or "Never". */
export function dayLabel(iso: string | null | undefined, never = "Never"): string {
  if (!iso) return never;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return never;
  if (d.toDateString() === new Date().toDateString()) return "Today";
  return `${String(d.getDate()).padStart(2, "0")} ${"Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ")[d.getMonth()]}`;
}

export function historyLine(h: TemplateVersion | undefined): string {
  if (!h) return "";
  const when = dayLabel(h.at, "");
  if (h.how === "from_shoot" && h.session_name) return `Updated from ${h.session_name} · ${when}`;
  if (h.how === "edited") return `Edited in Library · ${when}`;
  return `${h.summary} · ${when}`;
}

/** Save-on-blur state for one field: shows "✓ Saved" or a plain error with Retry. */
function useBlurSave(save: (v: string) => Promise<unknown>) {
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const last = useRef<string | null>(null);
  const attempt = async (v: string) => {
    last.current = v;
    setStatus("saving");
    try {
      await save(v);
      setStatus("saved");
      setError(null);
    } catch (e) {
      setStatus("error");
      setError((e as Error).message);
    }
  };
  return { status, error, attempt, retry: () => last.current != null && attempt(last.current) };
}

function SaveError({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div role="alert" className="lib-error">
      <span className="lib-glyph lib-ret">✕</span>
      <span className="lib-grow">Couldn't save: {error}. Your text stays here.</span>
      <button type="button" className="lib-btn lib-btn-s" onClick={onRetry}>
        Retry now
      </button>
    </div>
  );
}

/** A textarea that saves when it loses focus (only when the text changed). */
function BlurText(props: {
  label: ReactNode;
  ariaLabel: string;
  value: string;
  placeholder?: string;
  className?: string;
  onSave: (v: string) => Promise<unknown>;
  children?: (s: ReturnType<typeof useBlurSave>) => ReactNode;
}) {
  const [text, setText] = useState(props.value);
  const saved = useRef(props.value);
  useEffect(() => {
    setText(props.value);
    saved.current = props.value;
  }, [props.value]);
  const s = useBlurSave(props.onSave);
  return (
    <>
      <label className="lib-field">
        {props.label}
        <textarea
          aria-label={props.ariaLabel}
          className={props.className ?? "lib-textarea"}
          value={text}
          placeholder={props.placeholder}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => {
            if (text.trim() === saved.current.trim()) return;
            saved.current = text.trim();
            void s.attempt(text.trim());
          }}
        />
      </label>
      {s.status === "error" && s.error && <SaveError error={s.error} onRetry={() => void s.retry()} />}
      {props.children?.(s)}
    </>
  );
}

export function LibraryTab({ onNewShoot }: { onNewShoot: (preset?: { projectId?: string; templateId?: string }) => void }) {
  const [projects, reload] = useProjects();
  const [sel, setSelState] = useState<Sel>(() => loadSel() ?? { kind: "defaults" });
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [mine, setMine] = useState<string | null>(null);
  const setSel = (s: Sel) => {
    saveSel(s);
    setSelState(s);
  };
  useEffect(() => {
    api.prefs().then((v) => setMine(v.prefs.my_preferences ?? "")).catch(() => setMine(""));
  }, []);

  const live = (projects ?? []).filter((p) => !p.archived);
  const archived = (projects ?? []).filter((p) => p.archived);
  const templateProject = (tid: string) => live.find((p) => p.templates.some((t) => t.id === tid)) ?? null;
  const selProjectId = sel.kind === "project" ? sel.id : sel.kind === "template" ? templateProject(sel.id)?.id : undefined;
  const isOpen = (pid: string) => open[pid] ?? pid === selProjectId;

  let page: ReactNode = null;
  if (projects == null) page = <p className="lib-t3 lib-pad">Loading the library…</p>;
  else if (sel.kind === "defaults") page = <DefaultsPage mine={mine} onSaved={setMine} />;
  else if (!live.length && !archived.length) page = <FirstProject onCreated={async (p) => { await reload(); setSel({ kind: "project", id: p.id }); }} />;
  else if (sel.kind === "project") {
    const p = (projects ?? []).find((x) => x.id === sel.id);
    page = p ? (
      <ProjectPage key={p.id} project={p} projects={live} reload={reload} onOpenTemplate={(id) => setSel({ kind: "template", id })} onNewShoot={onNewShoot} />
    ) : (
      <p className="lib-t3 lib-pad">That project no longer exists.</p>
    );
  } else {
    const p = templateProject(sel.id);
    page = p ? (
      <TemplatePage key={sel.id} tid={sel.id} project={p} reload={reload} onProject={() => setSel({ kind: "project", id: p.id })} onOpenTemplate={(id) => setSel({ kind: "template", id })} onNewShoot={onNewShoot} />
    ) : (
      <p className="lib-t3 lib-pad">That template no longer exists.</p>
    );
  }

  return (
    <div className="lib-screen">
      <aside className="lib-rail" aria-label="Library">
        <div className="lib-rail-head">
          <h2 className="lib-rail-title">Library</h2>
          <span className="lib-mono lib-t3 lib-xs">⌘6</span>
        </div>
        <div className="lib-rail-scroll">
          <button type="button" className="lib-rail-item" aria-current={sel.kind === "defaults" ? "true" : undefined} onClick={() => setSel({ kind: "defaults" })}>
            <span className="lib-strong">Your defaults</span>
            <span className="lib-t3 lib-xs lib-ellipsis">{mine ? mine : "Empty · that’s fine"}</span>
          </button>
          <div className="lib-rail-section">
            <span className="lib-eyebrow">PROJECTS</span>
            <NewProjectButton onCreated={async (p) => { await reload(); setSel({ kind: "project", id: p.id }); }} />
          </div>
          {projects != null && !live.length && <span className="lib-t3 lib-small lib-rail-note">No projects yet</span>}
          {live.map((p) => (
            <div key={p.id} className="lib-stack-1">
              <button
                type="button"
                className="lib-rail-project"
                aria-current={sel.kind === "project" && sel.id === p.id ? "true" : undefined}
                aria-expanded={isOpen(p.id)}
                onClick={() => {
                  setOpen((o) => ({ ...o, [p.id]: true }));
                  setSel({ kind: "project", id: p.id });
                }}
              >
                <span
                  className="lib-caret"
                  aria-hidden="true"
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpen((o) => ({ ...o, [p.id]: !isOpen(p.id) }));
                  }}
                >
                  {isOpen(p.id) ? "▾" : "▸"}
                </span>
                <span className="lib-grow lib-strong">{p.name}</span>
                <span className="lib-mono lib-t3 lib-xs">{p.templates.length}</span>
              </button>
              {isOpen(p.id) &&
                p.templates.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className="lib-rail-template"
                    aria-current={sel.kind === "template" && sel.id === t.id ? "true" : undefined}
                    onClick={() => setSel({ kind: "template", id: t.id })}
                  >
                    <span className="lib-grow">{t.name}</span>
                    <span className="lib-mono lib-t3 lib-xs">{t.shot_count} shots</span>
                  </button>
                ))}
            </div>
          ))}
          {archived.length > 0 && (
            <div className="lib-rail-note lib-stack-1">
              <span className="lib-t3 lib-small">Archived ({archived.length})</span>
              {archived.map((p) => (
                <button key={p.id} type="button" className="lib-btn-text lib-small lib-left" onClick={() => setSel({ kind: "project", id: p.id })}>
                  {p.name}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="lib-rail-foot">
          <button type="button" className="lib-btn lib-btn-block" onClick={() => onNewShoot()}>
            New shoot… <span className="lib-kbd">⌘N</span>
          </button>
        </div>
      </aside>
      <main className="lib-main">{page}</main>
    </div>
  );
}

function NewProjectButton({ onCreated }: { onCreated: (p: Project) => void }) {
  const { run } = useApp();
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  if (!naming)
    return (
      <button type="button" className="lib-btn-text lib-small" onClick={() => setNaming(true)}>
        + New project
      </button>
    );
  return (
    <form
      className="lib-inline-form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!name.trim()) return;
        const p = await run("Add project", () => api.createProject({ name: name.trim() }));
        setNaming(false);
        setName("");
        if (p) onCreated(p);
      }}
    >
      <input className="lib-input lib-input-s" aria-label="New project name" placeholder="Project name" autoFocus value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setNaming(false)} />
    </form>
  );
}

// --- Your defaults -----------------------------------------------------------------------------
function DefaultsPage({ mine, onSaved }: { mine: string | null; onSaved: (v: string) => void }) {
  if (mine == null) return <p className="lib-t3 lib-pad">Loading…</p>;
  const empty = !mine.trim();
  return (
    <div className="lib-page lib-page-760">
      <div className="lib-stack-6">
        <span className="lib-eyebrow">APPLIES TO EVERYTHING YOU SHOOT</span>
        <h2 className="lib-h1">Your defaults</h2>
        <p className="lib-lede">
          Your taste across all your work. The coach reads it on every photo, but project, template and today's notes win when they disagree.
        </p>
      </div>
      <BlurText
        label={<span className="sr-only">Your defaults</span>}
        ariaLabel="Your defaults"
        className={empty ? "lib-textarea lib-textarea-xl lib-dashed" : "lib-textarea lib-textarea-xl"}
        value={mine}
        placeholder="Write anything that's true of how you like to work…"
        onSave={async (v) => {
          const r = await api.patchPrefs({ my_preferences: v });
          onSaved(r.prefs.my_preferences ?? "");
        }}
      >
        {(s) =>
          s.status === "saved" ? (
            <span className="lib-t3 lib-small">
              <span className="lib-mono lib-ok">✓</span> Saved · used from the next photo
            </span>
          ) : null
        }
      </BlurText>
      {empty && (
        <div className="lib-stack-12">
          <span className="lib-strong lib-body">Empty is fine. Most people leave this blank for weeks.</span>
          <span className="lib-t2">Add a line when you notice yourself telling the coach the same thing on every shoot, for example:</span>
          <div className="lib-stack-6 lib-t2">
            <span>· “I edit in Lightroom.”</span>
            <span>· “I usually shoot handheld.”</span>
            <span>· “Skip the theory, just tell me what to move.”</span>
          </div>
        </div>
      )}
      <div className="lib-key">
        <span className="lib-eyebrow lib-key-head">WHAT GOES WHERE · MOST SPECIFIC WINS</span>
        <span className="lib-mono lib-t1">Today</span>
        <span>Light and place for one shoot. Set in New shoot: “Overcast, no backdrop.”</span>
        <span className="lib-mono lib-t1">Template</span>
        <span>One product type: “Laces tidy, show the heel counter.”</span>
        <span className="lib-mono lib-t1">Project</span>
        <span>The look of a body of work: “Soft, blurred backgrounds; warm light.”</span>
        <span className="lib-mono lib-t1">Defaults</span>
        <span>You, everywhere. This page.</span>
      </div>
    </div>
  );
}

// --- first run -----------------------------------------------------------------------------------
function FirstProject({ onCreated }: { onCreated: (p: Project) => void }) {
  const { run } = useApp();
  const [name, setName] = useState("");
  return (
    <div className="lib-center">
      <form
        className="lib-stack-18 lib-maxw-560"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!name.trim()) return;
          const p = await run("Create project", () => api.createProject({ name: name.trim() }));
          if (p) onCreated(p);
        }}
      >
        <h2 className="lib-h1">Define a look once, reuse it every shoot</h2>
        <p className="lib-lede">
          A <b className="lib-strong lib-t1">project</b> is a body of work with one look, like your running blog. Inside it, a{" "}
          <b className="lib-strong lib-t1">template</b> holds the shot list for one kind of product, like shoes. Each new shoot starts from a template.
        </p>
        <label className="lib-field">
          <span className="lib-label">Project name</span>
          <input className="lib-input lib-input-l" placeholder="Running blog" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <div className="lib-row-8">
          <button type="submit" className="lib-btn lib-btn-pri lib-btn-l" disabled={!name.trim()}>
            Create project
          </button>
        </div>
      </form>
    </div>
  );
}

// --- project -------------------------------------------------------------------------------------
function ProjectPage(props: {
  project: Project;
  projects: Project[];
  reload: () => Promise<void>;
  onOpenTemplate: (id: string) => void;
  onNewShoot: (preset?: { projectId?: string; templateId?: string }) => void;
}) {
  const { run } = useApp();
  const p = props.project;
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(p.name);
  const [askArchive, setAskArchive] = useState(false);
  const [menu, setMenu] = useState<{ source: string | null } | null>(null);
  const sub = [
    `${p.templates.length} ${p.templates.length === 1 ? "template" : "templates"}`,
    `${p.shoot_count} ${p.shoot_count === 1 ? "shoot" : "shoots"}`,
    p.last_used ? `last shoot ${dayLabel(p.last_used).replace(/^Today$/, "today")}` : "not used yet",
  ].join(" · ");

  return (
    <div className="lib-page lib-page-1040">
      <div className="lib-head">
        <div className="lib-stack-6">
          <span className="lib-eyebrow">{p.archived ? "PROJECT · ARCHIVED" : "PROJECT"}</span>
          {renaming ? (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (name.trim() && name.trim() !== p.name) await run("Rename project", () => api.patchProject(p.id, { name: name.trim() }));
                setRenaming(false);
                await props.reload();
              }}
            >
              <input className="lib-input lib-input-title" aria-label="Project name" autoFocus value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setRenaming(false)} />
            </form>
          ) : (
            <h2 className="lib-h1">{p.name}</h2>
          )}
          <span className="lib-t3 lib-small">{sub}</span>
        </div>
        <div className="lib-head-actions">
          <button type="button" className="lib-btn" onClick={() => setRenaming(true)}>
            Rename
          </button>
          {p.archived ? (
            <button
              type="button"
              className="lib-btn"
              onClick={() => run("Restore project", async () => {
                await api.patchProject(p.id, { archived: false });
                await props.reload();
              })}
            >
              Restore
            </button>
          ) : (
            <>
              <button type="button" className="lib-btn" onClick={() => setAskArchive(true)}>
                Archive…
              </button>
              <button type="button" className="lib-btn lib-btn-pri" onClick={() => props.onNewShoot({ projectId: p.id })}>
                New shoot <span className="lib-kbd">⌘N</span>
              </button>
            </>
          )}
        </div>
      </div>
      {askArchive && (
        <div role="alertdialog" aria-label="Archive project" className="lib-confirm">
          <span className="lib-glyph lib-unc">!</span>
          <span className="lib-grow">
            Archive <b className="lib-bold">{p.name}</b>? Its {p.templates.length} templates stop appearing in New shoot. The {p.shoot_count} past shoots stay in
            Sessions, and you can restore it from Archived.
          </span>
          <button
            type="button"
            className="lib-btn lib-btn-pri lib-btn-s"
            onClick={() => run("Archive project", async () => {
              await api.patchProject(p.id, { archived: true });
              setAskArchive(false);
              await props.reload();
            })}
          >
            Archive project
          </button>
          <button type="button" className="lib-btn lib-btn-s" onClick={() => setAskArchive(false)}>
            Cancel
          </button>
        </div>
      )}
      <BlurText
        label={
          <span className="lib-row-between">
            <span className="lib-strong lib-body">The look</span>
            <span className="lib-t3 lib-xs">Used for every template in this project</span>
          </span>
        }
        ariaLabel={`${p.name}: the look`}
        className="lib-textarea lib-textarea-m"
        value={p.preferences}
        placeholder="E.g. “Soft, blurred backgrounds that separate the product; warm light”"
        onSave={async (v) => {
          await api.patchProject(p.id, { preferences: v });
          await props.reload();
        }}
      />
      {!p.archived && (
        <div className="lib-stack-10 lib-rel">
          <div className="lib-row-between lib-center-y">
            <span className="lib-strong lib-body">Templates</span>
            <button type="button" className="lib-btn lib-btn-s" aria-expanded={!!menu} onClick={() => setMenu(menu ? null : { source: null })}>
              New template <span className="lib-t3 lib-xxs">▾</span>
            </button>
          </div>
          {menu && (
            <NewTemplateMenu
              project={p}
              source={menu.source}
              onPick={(source) => setMenu({ source })}
              onClose={() => setMenu(null)}
              onCreated={async (t) => {
                setMenu(null);
                await props.reload();
                props.onOpenTemplate(t.id);
              }}
            />
          )}
          <div className="lib-table" role="table" aria-label={`${p.name} templates`}>
            <div className="lib-trow lib-thead" role="row">
              <span role="columnheader">TEMPLATE</span>
              <span role="columnheader">SHOTS</span>
              <span role="columnheader">VERSION</span>
              <span role="columnheader">LAST USED</span>
              <span role="columnheader">SHOOTS</span>
              <span role="columnheader">
                <span className="sr-only">Actions</span>
              </span>
            </div>
            {p.templates.map((t) => (
              <div key={t.id} className="lib-trow" role="row" data-testid={`template-${t.name}`}>
                <span role="cell" className="lib-stack-2 lib-minw0">
                  <span className="lib-strong lib-body">{t.name}</span>
                  <span className="lib-t3 lib-xs">{historyLine(t.history?.[t.history.length - 1])}</span>
                </span>
                <span role="cell" className="lib-mono lib-small">{t.shot_count}</span>
                <span role="cell" className="lib-mono lib-small">v{t.version}</span>
                <span role="cell" className="lib-t2 lib-small">{dayLabel(t.last_used)}</span>
                <span role="cell" className="lib-mono lib-small">{t.shoot_count}</span>
                <span role="cell" className="lib-tactions">
                  <button type="button" className="lib-btn-text lib-small" aria-label={`Edit ${t.name}`} onClick={() => props.onOpenTemplate(t.id)}>
                    Edit
                  </button>
                  <button type="button" className="lib-btn-text lib-small lib-t2" aria-label={`Duplicate ${t.name}`} onClick={() => setMenu({ source: t.id })}>
                    Duplicate
                  </button>
                </span>
              </div>
            ))}
            {!p.templates.length && <p className="lib-t3 lib-small lib-pad-y">No templates yet. Start one from New template.</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function NewTemplateMenu(props: {
  project: Project;
  source: string | null;
  onPick: (source: string) => void;
  onClose: () => void;
  onCreated: (t: ShootTemplate) => void;
}) {
  const { run } = useApp();
  const src = props.project.templates.find((t) => t.id === props.source) ?? null;
  const [name, setName] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        props.onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [props]);
  const create = async (copyFrom: string | null, n: string) => {
    const t = await run("New template", () => api.createTemplate(props.project.id, { name: n, copy_from: copyFrom }));
    if (t) props.onCreated(t);
  };
  return (
    <div ref={ref} className="lib-menu" role="dialog" aria-label="New template">
      <button type="button" className="lib-menu-item" onClick={() => void create(null, "Untitled template")}>
        <span className="lib-strong">Blank template</span>
        <span className="lib-t3 lib-xs">Start with no shots</span>
      </button>
      <div className="lib-menu-sep" />
      <span className="lib-eyebrow lib-menu-label">DUPLICATE · THE USUAL WAY</span>
      {props.project.templates.map((t) => (
        <button key={t.id} type="button" className="lib-menu-row" aria-pressed={t.id === props.source} onClick={() => props.onPick(t.id)}>
          <span className="lib-grow">{t.name}</span>
          <span className="lib-mono lib-t3 lib-xs">
            {t.shot_count} shots · v{t.version}
          </span>
        </button>
      ))}
      {src && (
        <form
          className="lib-menu-foot"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) void create(src.id, name.trim());
          }}
        >
          <span className="lib-small lib-t2">
            Copy <b className="lib-strong lib-t1">{src.name}</b> ({src.shot_count} shots and its preferences) as:
          </span>
          <input className="lib-input lib-input-focus" aria-label="New template name" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
          <div className="lib-row-8">
            <button type="submit" className="lib-btn lib-btn-pri lib-btn-s" disabled={!name.trim()}>
              Create {name.trim() || "copy"} <span className="lib-kbd">↵</span>
            </button>
            <span className="lib-t3 lib-xs">Starts at v1. {src.name} is unchanged.</span>
          </div>
        </form>
      )}
    </div>
  );
}

// --- template editor -----------------------------------------------------------------------------
const MAX_CRITERIA = 6;

function TemplatePage(props: {
  tid: string;
  project: Project;
  reload: () => Promise<void>;
  onProject: () => void;
  onOpenTemplate: (id: string) => void;
  onNewShoot: (preset?: { projectId?: string; templateId?: string }) => void;
}) {
  const { run } = useApp();
  const [t, setT] = useState<ShootTemplate | null>(null);
  const [draft, setDraft] = useState<TemplateShot[]>([]);
  const [si, setSi] = useState(0);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState("");
  const [dupName, setDupName] = useState<string | null>(null);
  const summary: TemplateSummary | undefined = props.project.templates.find((x) => x.id === props.tid);
  const load = async () => {
    const full = await run("Open template", () => api.template(props.tid));
    if (full) {
      setT(full);
      setDraft(full.shots);
      setName(full.name);
    }
  };
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.tid]);
  const dirty = useMemo(() => t != null && JSON.stringify(draft) !== JSON.stringify(t.shots), [draft, t]);

  if (!t)
    return (
      <div className="lib-page">
        <div className="lib-tpl-grid">
          <div className="lib-stack-8">
            <div className="lib-skel lib-skel-70" />
            <div className="lib-skel" />
            <div className="lib-skel lib-o7" />
            <div className="lib-skel lib-o5" />
          </div>
          <div className="lib-stack-10">
            <div className="lib-skel lib-skel-46 lib-w60" />
            <div className="lib-skel lib-skel-72" />
            <span className="lib-t3 lib-small">Loading {summary?.name ?? "template"}…</span>
          </div>
        </div>
      </div>
    );

  const last = t.history[t.history.length - 1];
  const sub = [
    t.history.length ? historyLine(last) : "New · not used yet",
    `${t.shots.length} shots`,
    summary ? (summary.shoot_count ? `used in ${summary.shoot_count} ${summary.shoot_count === 1 ? "shoot" : "shoots"}` : "not used yet") : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const cur = draft[Math.min(si, draft.length - 1)] ?? null;
  const setShot = (i: number, patch: Partial<TemplateShot>) => setDraft((d) => d.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= draft.length) return;
    setDraft((d) => {
      const n = [...d];
      [n[i], n[j]] = [n[j], n[i]];
      return n;
    });
    setSi(j);
  };
  const onRowKey = (e: KeyboardEvent, i: number) => {
    if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault();
    move(i, e.key === "ArrowUp" ? -1 : 1);
  };
  const addShot = () => {
    setDraft((d) => [...d, { title: `Shot ${d.length + 1}`, purpose: "", must_show: [], framing: "", criteria: [], sharp_regions: [] }]);
    setSi(draft.length);
  };
  const save = () =>
    run("Save template", async () => {
      const next = await api.patchTemplate(t.id, { shots: draft });
      setT(next);
      setDraft(next.shots);
      await props.reload();
    });

  return (
    <div className="lib-page lib-page-tpl">
      <div className="lib-head">
        <div className="lib-stack-6">
          <span className="lib-t3 lib-small">
            <button type="button" className="lib-btn-text lib-small" onClick={props.onProject}>
              {props.project.name}
            </button>{" "}
            › template
          </span>
          <div className="lib-row-baseline lib-gap-12">
            {renaming ? (
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (name.trim() && name.trim() !== t.name) {
                    const r = await run("Rename template", () => api.patchTemplate(t.id, { name: name.trim() }));
                    if (r) setT({ ...t, name: r.name });
                    await props.reload();
                  }
                  setRenaming(false);
                }}
              >
                <input className="lib-input lib-input-title" aria-label="Template name" autoFocus value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setRenaming(false)} />
              </form>
            ) : (
              <h2 className="lib-h1">
                <button type="button" className="lib-title-btn" title="Rename" onClick={() => setRenaming(true)}>
                  {t.name}
                </button>
              </h2>
            )}
            <span className="lib-ver">v{t.version}</span>
          </div>
          <span className="lib-t3 lib-small">{sub}</span>
        </div>
        <div className="lib-head-actions">
          <button type="button" className="lib-btn" onClick={() => setDupName(dupName == null ? `${t.name} copy` : null)}>
            Duplicate
          </button>
          <button type="button" className="lib-btn lib-btn-pri" onClick={() => props.onNewShoot({ projectId: props.project.id, templateId: t.id })}>
            New shoot from this <span className="lib-kbd">⌘N</span>
          </button>
        </div>
      </div>
      {dupName != null && (
        <form
          className="lib-confirm"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!dupName.trim()) return;
            const n = await run("Duplicate template", () => api.createTemplate(props.project.id, { name: dupName.trim(), copy_from: t.id }));
            setDupName(null);
            if (n) {
              await props.reload();
              props.onOpenTemplate(n.id);
            }
          }}
        >
          <span className="lib-small lib-t2">Copy {t.name} as</span>
          <input className="lib-input lib-grow" aria-label="New template name" autoFocus value={dupName} onChange={(e) => setDupName(e.target.value)} />
          <button type="submit" className="lib-btn lib-btn-pri lib-btn-s" disabled={!dupName.trim()}>
            Create copy
          </button>
          <button type="button" className="lib-btn lib-btn-s" onClick={() => setDupName(null)}>
            Cancel
          </button>
        </form>
      )}
      {dirty && (
        <div className="lib-dirty" role="status">
          <span className="lib-glyph lib-unc">◆</span>
          <span className="lib-grow">Unsaved changes to the shot list. Saving makes v{t.version + 1}; shoots already started keep their own copy.</span>
          <button type="button" className="lib-btn lib-btn-pri lib-btn-s" onClick={() => void save()}>
            Save as v{t.version + 1}
          </button>
          <button type="button" className="lib-btn lib-btn-s" onClick={() => setDraft(t.shots)}>
            Discard
          </button>
        </div>
      )}
      <div className="lib-tpl-grid">
        <div className="lib-stack-14">
          <BlurText
            label={<span className="lib-label">Preferences for this product type</span>}
            ariaLabel={`${t.name}: preferences`}
            className="lib-textarea lib-textarea-s"
            value={t.preferences}
            placeholder="e.g. Laces tidy. Lateral side faces the camera."
            onSave={async (v) => {
              const r = await api.patchTemplate(t.id, { preferences: v });
              setT((x) => (x ? { ...x, preferences: r.preferences } : x));
              await props.reload();
            }}
          />
          <div className="lib-row-between lib-mt-4">
            <span className="lib-strong lib-body">Shot list</span>
            <span className="lib-t3 lib-xs">⌥↑ ⌥↓ to reorder</span>
          </div>
          {!draft.length ? (
            <div className="lib-empty">
              <span className="lib-strong lib-body">No shots yet</span>
              <span className="lib-small lib-t2">
                List the photos you'd want every time you review this kind of product. Start with the hero; 4–8 shots is typical.
              </span>
              <div className="lib-row-8">
                <button type="button" className="lib-btn lib-btn-pri lib-btn-s" onClick={addShot}>
                  + Add first shot
                </button>
                <CopyShotsFrom project={props.project} exclude={t.id} onCopy={(shots) => setDraft(shots)} />
              </div>
            </div>
          ) : (
            <>
              <ol className="lib-stack-2" aria-label="Shots">
                {draft.map((s, i) => (
                  <li key={i}>
                    <button
                      type="button"
                      className="lib-shot-row"
                      aria-current={i === si ? "true" : undefined}
                      onClick={() => setSi(i)}
                      onKeyDown={(e) => onRowKey(e, i)}
                    >
                      <span className="lib-mono lib-t3 lib-small" aria-hidden="true">⋮⋮</span>
                      <span className="lib-mono lib-t3 lib-xxs lib-num">{i + 1}</span>
                      <span className="lib-stack-0 lib-grow lib-minw0">
                        <span className="lib-strong">{s.title}</span>
                        <span className="lib-t3 lib-xs lib-ellipsis">
                          {s.criteria.length} criteria{s.framing ? ` · ${s.framing}` : ""}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
              <button type="button" className="lib-btn-dashed" onClick={addShot}>
                + Add shot
              </button>
            </>
          )}
        </div>
        {cur && (
          <ShotEditor
            key={si}
            shot={cur}
            onChange={(patch) => setShot(si, patch)}
            onRemove={() => {
              setDraft((d) => d.filter((_, j) => j !== si));
              setSi(Math.max(0, si - 1));
            }}
            onMove={(dir) => move(si, dir)}
            canUp={si > 0}
            canDown={si < draft.length - 1}
            history={t.history}
          />
        )}
      </div>
    </div>
  );
}

function CopyShotsFrom({ project, exclude, onCopy }: { project: Project; exclude: string; onCopy: (shots: TemplateShot[]) => void }) {
  const { run } = useApp();
  const [open, setOpen] = useState(false);
  const others = project.templates.filter((t) => t.id !== exclude && t.shot_count > 0);
  if (!others.length) return null;
  if (!open)
    return (
      <button type="button" className="lib-btn lib-btn-s" onClick={() => setOpen(true)}>
        Copy shots from…
      </button>
    );
  return (
    <select
      className="lib-input lib-input-s"
      aria-label="Copy shots from"
      autoFocus
      defaultValue=""
      onChange={async (e) => {
        const full = await run("Copy shots", () => api.template(e.target.value));
        if (full) onCopy(full.shots);
        setOpen(false);
      }}
    >
      <option value="" disabled>
        Pick a template…
      </option>
      {others.map((t) => (
        <option key={t.id} value={t.id}>
          {t.name} · {t.shot_count} shots
        </option>
      ))}
    </select>
  );
}

function ShotEditor(props: {
  shot: TemplateShot;
  onChange: (patch: Partial<TemplateShot>) => void;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
  canUp: boolean;
  canDown: boolean;
  history: TemplateVersion[];
}) {
  const s = props.shot;
  const [must, setMust] = useState<string | null>(null);
  const crit = s.criteria;
  const setCrit = (next: Criterion[]) => props.onChange({ criteria: next });
  const addMust = () => {
    const v = (must ?? "").trim();
    if (v && !s.must_show.includes(v)) props.onChange({ must_show: [...s.must_show, v] });
    setMust(null);
  };
  return (
    <div className="lib-card lib-stack-16">
      <div className="lib-grid-2">
        <label className="lib-field lib-span-2">
          <span className="lib-label">Title</span>
          <input className="lib-input lib-input-title-s" value={s.title} onChange={(e) => props.onChange({ title: e.target.value })} />
        </label>
        <label className="lib-field lib-span-2">
          <span className="lib-label">Purpose — why the reader needs it</span>
          <input className="lib-input" value={s.purpose} onChange={(e) => props.onChange({ purpose: e.target.value })} />
        </label>
        <label className="lib-field">
          <span className="lib-label">Framing</span>
          <input className="lib-input" value={s.framing} onChange={(e) => props.onChange({ framing: e.target.value })} />
        </label>
        <div className="lib-field">
          <span className="lib-label">Must show</span>
          <div className="lib-chips">
            {s.must_show.map((m) => (
              <span key={m} className="lib-chip">
                {m}
                <button type="button" className="lib-chip-x" aria-label={`Remove ${m}`} onClick={() => props.onChange({ must_show: s.must_show.filter((x) => x !== m) })}>
                  ×
                </button>
              </span>
            ))}
            {must == null ? (
              <button type="button" className="lib-chip lib-chip-add" onClick={() => setMust("")}>
                + Add
              </button>
            ) : (
              <input
                className="lib-input lib-input-chip"
                aria-label="Must show"
                autoFocus
                value={must}
                onChange={(e) => setMust(e.target.value)}
                onBlur={addMust}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addMust();
                  } else if (e.key === "Escape") setMust(null);
                }}
              />
            )}
          </div>
        </div>
      </div>
      <div className="lib-stack-8">
        <div className="lib-row-between">
          <span className="lib-label">Acceptance criteria</span>
          <span className="lib-t3 lib-xs">{crit.length} of 2–6 · the coach checks each</span>
        </div>
        {crit.map((c, i) => (
          <div key={c.id} className="lib-row-10">
            <span className="lib-mono lib-t3 lib-num">{i + 1}</span>
            <input
              className="lib-input lib-grow"
              aria-label={`Criterion ${i + 1}`}
              value={c.text}
              onChange={(e) => setCrit(crit.map((x) => (x.id === c.id ? { ...x, text: e.target.value } : x)))}
            />
            <button type="button" className="lib-icon-btn" aria-label={`Remove criterion ${i + 1}`} onClick={() => setCrit(crit.filter((x) => x.id !== c.id))}>
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          className="lib-btn-text lib-small lib-self-start"
          disabled={crit.length >= MAX_CRITERIA}
          onClick={() => setCrit([...crit, { id: nextCriterionId(crit), text: "" }])}
        >
          + Add criterion
        </button>
      </div>
      <div className="lib-row-8">
        <button type="button" className="lib-btn lib-btn-s" disabled={!props.canUp} onClick={() => props.onMove(-1)}>
          ↑ Move up
        </button>
        <button type="button" className="lib-btn lib-btn-s" disabled={!props.canDown} onClick={() => props.onMove(1)}>
          ↓ Move down
        </button>
        <button type="button" className="lib-btn-text lib-small lib-ret lib-push" onClick={props.onRemove}>
          Remove shot
        </button>
      </div>
      {props.history.length > 0 && (
        <div className="lib-versions">
          <span className="lib-eyebrow">VERSIONS</span>
          {[...props.history].reverse().map((h, i) => (
            <div key={h.version} className="lib-version-row">
              <span className={i === 0 ? "lib-mono lib-bold" : "lib-mono"}>v{h.version}</span>
              <span className="lib-t2">
                {dayLabel(h.at, "")}
                {h.how === "from_shoot" && h.session_name ? ` · from ${h.session_name}` : h.how === "edited" ? " · in Library" : h.how === "created" ? " · created" : " · duplicated"}
              </span>
              <span className="lib-t3">{h.summary}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
