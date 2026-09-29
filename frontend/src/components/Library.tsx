import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Project } from "../api/types";
import { useApp } from "../AppContext";

/** Shared project data, and the shoot's origin panel. The Library itself is LibraryTab.tsx. */

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
