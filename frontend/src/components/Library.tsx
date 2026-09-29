import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Project, TemplateSummary } from "../api/types";
import { useApp } from "../AppContext";

/** Projects → shoot templates, plus "Your defaults". A working version until the design brief's Library lands. */

export function useProjects(): [Project[] | null, () => Promise<void>] {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const load = async () => {
    try {
      setProjects(await api.projects());
    } catch {
      setProjects([]);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  return [projects, load];
}

/** A text area that saves when it loses focus (and only if the text changed). */
function SavedText({
  label,
  value,
  placeholder,
  onSave,
  rows = 2,
}: {
  label: string;
  value: string;
  placeholder?: string;
  onSave: (v: string) => Promise<unknown>;
  rows?: number;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <label className="wf-field">
      <span className="wf-label">{label}</span>
      <textarea
        className="wf-input"
        rows={rows}
        value={text}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          if (text.trim() !== value.trim()) void onSave(text.trim());
        }}
      />
    </label>
  );
}

function NameInput({ label, submitLabel, onSubmit }: { label: string; submitLabel: string; onSubmit: (name: string) => Promise<unknown> }) {
  const [name, setName] = useState("");
  return (
    <form
      className="wf-row wf-gap-8"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!name.trim()) return;
        await onSubmit(name.trim());
        setName("");
      }}
    >
      <input className="wf-input" aria-label={label} placeholder={label} value={name} onChange={(e) => setName(e.target.value)} />
      <button type="submit" className="wf-btn" disabled={!name.trim()}>
        {submitLabel}
      </button>
    </form>
  );
}

function TemplateRow({ t, onChanged }: { t: TemplateSummary; onChanged: () => Promise<void> }) {
  const { run } = useApp();
  const [duplicating, setDuplicating] = useState(false);
  return (
    <li className="wf-lib-template" data-testid={`template-${t.name}`}>
      <div className="wf-row-baseline wf-gap-8">
        <span className="wf-strong">{t.name}</span>
        <span className="wf-t3 wf-xs wf-mono">
          {t.shot_count} shots · v{t.version}
        </span>
        <button type="button" className="wf-btn-text wf-xs" onClick={() => setDuplicating((d) => !d)}>
          Duplicate…<span className="sr-only"> {t.name}</span>
        </button>
      </div>
      <span className="wf-t3 wf-xs">{t.shot_titles.join(" · ")}</span>
      <SavedText
        label={`${t.name}: preferences`}
        value={t.preferences}
        placeholder="Taste for this product type, e.g. “Laces tidy; show the heel counter”"
        onSave={(v) => run("Save template preferences", async () => {
          await api.patchTemplate(t.id, { preferences: v });
          await onChanged();
        })}
      />
      {duplicating && (
        <NameInput
          label="New template name"
          submitLabel="Create copy"
          onSubmit={(name) => run("Duplicate template", async () => {
            await api.createTemplate(t.project_id, { name, copy_from: t.id });
            setDuplicating(false);
            await onChanged();
          })}
        />
      )}
    </li>
  );
}

export function LibraryPanel() {
  const { run } = useApp();
  const [projects, reload] = useProjects();
  const [mine, setMine] = useState<string | null>(null);
  useEffect(() => {
    api.prefs().then((v) => setMine(v.prefs.my_preferences ?? "")).catch(() => setMine(""));
  }, []);

  return (
    <section className="wf-stack-18 wf-lib" aria-labelledby="library-h">
      <h2 className="wf-title-l" id="library-h">
        Library
      </h2>
      {mine != null && (
        <SavedText
          label="Your defaults (all projects)"
          value={mine}
          placeholder="How you like your photos, across everything. Empty is fine; add to it as your taste develops."
          onSave={(v) => run("Save your defaults", async () => {
            const r = await api.patchPrefs({ my_preferences: v });
            setMine(r.prefs.my_preferences ?? "");
          })}
        />
      )}
      {projects == null && <p className="wf-t3">Loading projects…</p>}
      {projects?.map((p) => (
        <div key={p.id} className="wf-lib-project wf-stack-12" data-testid={`project-${p.name}`}>
          <h3 className="wf-strong">{p.name}</h3>
          <SavedText
            label={`${p.name}: the project's look`}
            value={p.preferences}
            placeholder="E.g. “Soft, blurred backgrounds that separate the product; warm light”"
            onSave={(v) => run("Save project preferences", async () => {
              await api.patchProject(p.id, { preferences: v });
              await reload();
            })}
          />
          <ul className="wf-stack-12 wf-lib-templates" aria-label={`${p.name} shoot templates`}>
            {p.templates.map((t) => (
              <TemplateRow key={t.id} t={t} onChanged={reload} />
            ))}
          </ul>
          <NameInput
            label="New blank template"
            submitLabel="Add template"
            onSubmit={(name) => run("Add template", async () => {
              await api.createTemplate(p.id, { name });
              await reload();
            })}
          />
        </div>
      ))}
      <NameInput
        label="New project name"
        submitLabel="Add project"
        onSubmit={(name) => run("Add project", async () => {
          await api.createProject({ name });
          await reload();
        })}
      />
    </section>
  );
}

/** In a shoot: where it came from (Project › Template vN), day notes, and saving the shot list back. */
export function ShootOrigin() {
  const { sid, state, run, refresh, toast } = useApp();
  const [projects, reload] = useProjects();
  const [confirming, setConfirming] = useState(false);
  const [asNew, setAsNew] = useState(false);
  if (!sid || !state) return null;
  const s = state.session;
  const project = projects?.find((p) => p.id === s.project_id) ?? null;
  const template = project?.templates.find((t) => t.id === s.template_id) ?? null;
  const behind = template != null && s.template_version != null && template.version > s.template_version;

  return (
    <div className="wf-stack-12 wf-origin" data-testid="shoot-origin">
      <span className="wf-t3 wf-xs">
        From{" "}
        <span className="wf-strong">
          {project?.name ?? "no project"}
          {template ? ` › ${template.name} · v${s.template_version ?? template.version}` : " › blank"}
        </span>
        {behind && ` (template is now v${template.version})`}
      </span>
      <div className="wf-row wf-gap-8">
        {template && (
          <button type="button" className="wf-btn" onClick={() => setConfirming(true)}>
            Save to template
          </button>
        )}
        {project && (
          <button type="button" className="wf-btn-text wf-xs" onClick={() => setAsNew((v) => !v)}>
            Save as new template…
          </button>
        )}
      </div>
      {confirming && template && (
        <div role="alertdialog" aria-label="Save to template" className="wf-stack-12 wf-confirm">
          <span className="wf-small">
            Replace “{template.name}” v{template.version}'s {template.shot_count} shots with this shoot's {state.shots.length}?
            Future shoots from it start from this list; past shoots are unchanged.
          </span>
          <div className="wf-row wf-gap-8">
            <button
              type="button"
              className="wf-btn wf-btn-pri"
              onClick={() =>
                run("Save to template", async () => {
                  const t = await api.saveToTemplate(sid);
                  setConfirming(false);
                  toast({ glyph: "✓", text: `Saved to ${t.name} · v${t.version}`, tone: "ok" });
                  await Promise.all([reload(), refresh()]);
                })
              }
            >
              Save as v{template.version + 1}
            </button>
            <button type="button" className="wf-btn" onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {asNew && (
        <NameInput
          label="New template name"
          submitLabel="Save as new"
          onSubmit={(name) =>
            run("Save as new template", async () => {
              const t = await api.saveToTemplate(sid, name);
              setAsNew(false);
              toast({ glyph: "✓", text: `New template “${t.name}”`, tone: "ok" });
              await Promise.all([reload(), refresh()]);
            })
          }
        />
      )}
      <SavedText
        label="Day notes (this shoot only)"
        value={s.shoot_preferences ?? ""}
        placeholder="E.g. “Outdoors, no backdrop; overcast”"
        onSave={(v) =>
          run("Save day notes", async () => {
            await api.patchSession(sid, { shoot_preferences: v });
            await refresh();
          })
        }
      />
    </div>
  );
}
