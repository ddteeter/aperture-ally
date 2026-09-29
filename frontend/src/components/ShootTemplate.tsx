import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { ShotListChange } from "../api/types";
import { useApp } from "../AppContext";
import { useShortcuts } from "../lib/keys";
import { useProjects } from "./Library";
import "./shoottemplate.css";

/** A shoot's link to its template (Shoot v2, group 1c): origin line, "N shots changed · Save…", the save
 *  dialogs, and today's notes. Nothing is saved to a template without an explicit button press. */

export function openTemplateInLibrary(templateId: string) {
  try {
    localStorage.setItem("aperture-ally.library", JSON.stringify({ kind: "template", id: templateId }));
  } catch {
    /* ignore */
  }
  window.location.hash = "library";
}

/** Per shot row (1-based position): a short mark for how it differs from the template. */
export function shotMarks(changes: ShotListChange[]): Map<number, string> {
  const out = new Map<number, string>();
  for (const c of changes) {
    const n = Number(c.title.split(" · ")[0]);
    if (!Number.isFinite(n) || c.g === "−") continue;
    if (c.g === "+") out.set(n, "◆ added in this shoot");
    else {
      const added = (c.detail.match(/Criterion added/g) ?? []).length;
      const removed = (c.detail.match(/Criterion removed/g) ?? []).length;
      const bits = [added ? `+${added} ${added === 1 ? "criterion" : "criteria"}` : "", removed ? `−${removed}` : ""].filter(Boolean);
      out.set(n, `◆ edited${bits.length ? `: ${bits.join(" ")}` : ""}`);
    }
  }
  return out;
}

type DialogKind = "save" | "new" | null;

/** Origin line + changes chip + dialogs. `compact` is the Shoot rail; otherwise the Shot list tab header. */
export function ShootOriginBar({ compact = false }: { compact?: boolean }) {
  const { state } = useApp();
  const [dialog, setDialog] = useState<DialogKind>(null);
  const o = state?.origin;
  useShortcuts((s) => {
    if (s.kind === "saveTemplate" && o?.template_id) {
      setDialog("save");
      return true;
    }
    return false;
  });
  if (!state || !o) return null;
  const n = o.changes.length;
  const ver = o.template_version ?? o.template_current_version;
  return (
    <div className={compact ? "st-origin st-compact" : "st-origin"} data-testid="shoot-origin">
      <span className="st-from" title="This shoot's shot list was copied from this template">
        from{" "}
        {o.template_id ? (
          <button type="button" className="st-link" onClick={() => openTemplateInLibrary(o.template_id!)}>
            {o.project_name} › {o.template_name} v{ver}
          </button>
        ) : (
          <span>{o.project_name ? `${o.project_name} › ` : ""}a blank shot list</span>
        )}
      </span>
      {n > 0 && o.template_id && (
        <button type="button" className="st-chip" onClick={() => setDialog("save")}>
          <span className="st-chip-g" aria-hidden="true">◆</span>
          {n} {n === 1 ? "shot" : "shots"} changed · Save…
        </button>
      )}
      {!o.template_id && o.project_id && state.shots.length > 0 && (
        <button type="button" className="st-link st-small" onClick={() => setDialog("new")}>
          Save as a template…
        </button>
      )}
      {dialog && <SaveDialog kind={dialog} onKind={setDialog} onClose={() => setDialog(null)} />}
    </div>
  );
}

function Modal({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, button")?.focus();
    return () => prev?.focus?.();
  }, []);
  return (
    <div className="st-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        className="st-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={label}
        onKeyDown={(e) => {
          e.stopPropagation(); // shortcuts underneath stay quiet
          if (e.key === "Escape") {
            e.preventDefault();
            onClose();
          }
        }}
      >
        {children}
      </div>
    </div>
  );
}

function SaveDialog({ kind, onKind, onClose }: { kind: "save" | "new"; onKind: (k: DialogKind) => void; onClose: () => void }) {
  const { sid, state, run, refresh, refreshSessions, toast } = useApp();
  const [projects] = useProjects();
  const o = state!.origin!;
  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState(o.project_id ?? "");
  const notes = state!.session.shoot_preferences?.trim() ?? "";
  const cur = o.template_current_version ?? 1;
  const tplPrefs = projects?.flatMap((p) => p.templates).find((t) => t.id === o.template_id)?.preferences ?? "";
  const done = async (text: string) => {
    toast({ glyph: "✓", text, tone: "ok" });
    onClose();
    await Promise.all([refresh(), refreshSessions()]);
  };

  if (kind === "save")
    return (
      <Modal label={`Save changes to ${o.template_name}`} onClose={onClose}>
        <div className="st-stack-6">
          <span className="st-title">Save changes to {o.template_name}?</span>
          <span className="st-lede">
            The template goes from <b className="st-mono">v{cur}</b> to <b className="st-mono">v{cur + 1}</b>. Future shoots start with these changes. Past
            shoots keep their own copies.
          </span>
        </div>
        <ul className="st-changes" aria-label="Changes">
          {o.changes.map((c, i) => (
            <li key={i}>
              <span className="st-change-g" aria-hidden="true">{c.g}</span>
              <span className="st-stack-2">
                <span className="st-change-title">{c.title}</span>
                <span className="st-change-detail">{c.detail}</span>
              </span>
            </li>
          ))}
        </ul>
        {notes && <span className="st-note">Not saved: today's notes (“{notes.length > 40 ? `${notes.slice(0, 40)}…` : notes}”) stay with this shoot.</span>}
        <div className="st-actions">
          <button
            type="button"
            className="st-btn st-btn-pri"
            onClick={() =>
              run("Save to template", async () => {
                const t = await api.saveToTemplate(sid!);
                await done(`Saved to ${t.name} · v${t.version}`);
              })
            }
          >
            Save as v{cur + 1}
          </button>
          <button type="button" className="st-btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="st-link st-push" onClick={() => onKind("new")}>
            Save as new template instead
          </button>
        </div>
      </Modal>
    );

  const live = (projects ?? []).filter((p) => !p.archived);
  const edited = o.changes.filter((c) => c.g === "~").length;
  const added = o.changes.filter((c) => c.g === "+");
  const shotsLine = o.template_id
    ? `${state!.shots.length}: ${state!.shots.length - added.length} from ${o.template_name} v${o.template_version ?? cur}${edited ? ` (${edited} edited)` : ""}${
        added.length ? `, plus ${added.map((a) => a.title.split(" · ").slice(1).join(" · ")).join(", ")}` : ""
      }`
    : `${state!.shots.length} from this shoot`;
  return (
    <Modal label="Save as a new template" onClose={onClose}>
      <form
        className="st-stack-16"
        onSubmit={(e) => {
          e.preventDefault();
          if (!name.trim()) return;
          void run("Save as new template", async () => {
            const t = await api.saveToTemplate(sid!, name.trim(), projectId || null);
            await done(`New template “${t.name}”`);
          });
        }}
      >
        <div className="st-stack-6">
          <span className="st-title">Save as a new template</span>
          <span className="st-lede">
            {o.template_id ? `${o.template_name} v${cur} stays as it is. ` : ""}From now on this shoot is linked to the new template.
          </span>
        </div>
        <label className="st-field">
          <span className="st-label">Name</span>
          <input className="st-input" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        {live.length > 1 && (
          <div className="st-field" role="radiogroup" aria-label="Project">
            <span className="st-label">Project</span>
            <div className="st-row-6">
              {live.map((p) => (
                <button key={p.id} type="button" role="radio" aria-checked={p.id === projectId} className="st-pick" onClick={() => setProjectId(p.id)}>
                  {p.name}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="st-summary">
          <span className="st-t3">Shots</span>
          <span>{shotsLine}</span>
          <span className="st-t3">Preferences</span>
          <span>{tplPrefs ? `“${tplPrefs}” Edit later in Library.` : "None yet. Add them later in Library."}</span>
          <span className="st-t3">Starts at</span>
          <span className="st-mono">v1</span>
        </div>
        <div className="st-actions">
          <button type="submit" className="st-btn st-btn-pri" disabled={!name.trim()}>
            Create {name.trim() ? `“${name.trim()}”` : "template"}
          </button>
          <button type="button" className="st-btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** Today's notes: this shoot only, most specific. Edited from a small popover (N). */
export function TodayNotes() {
  const { sid, state, run, refresh } = useApp();
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  useShortcuts((s) => {
    if (s.kind === "notes" && state) {
      setOpen(true);
      return true;
    }
    return false;
  });
  if (!state || !sid) return null;
  const text = state.session.shoot_preferences?.trim() ?? "";
  const nextSeq = Math.max(0, ...state.captures.map((c) => c.seq)) + 1;
  const lastSeq = nextSeq - 1;
  return (
    <div className="st-today" data-testid="today-notes" ref={boxRef}>
      <div className="st-row-between">
        <span className="st-eyebrow">TODAY</span>
        <button type="button" className="st-link st-small" aria-keyshortcuts="N" onClick={() => setOpen(true)}>
          Edit <span className="st-mono st-t3">N</span>
        </button>
      </div>
      <span className="st-today-text">{text || <span className="st-t3">No notes for today. Light, place, anything different.</span>}</span>
      {open && (
        <NotesPopover
          anchor={boxRef.current?.getBoundingClientRect() ?? null}
          initial={text}
          hint={`Used from the next photo (#${nextSeq}).${lastSeq > 0 ? ` #${lastSeq} keeps the advice it got.` : ""} Shortcut keys are off while you type.`}
          onClose={() => setOpen(false)}
          onSave={(v) =>
            run("Save today's notes", async () => {
              await api.patchSession(sid, { shoot_preferences: v });
              setOpen(false);
              await refresh();
            })
          }
        />
      )}
    </div>
  );
}

function NotesPopover(props: { anchor: DOMRect | null; initial: string; hint: string; onSave: (v: string) => void; onClose: () => void }) {
  const { anchor, initial, hint, onSave, onClose } = props;
  const [v, setV] = useState(initial);
  // Fixed to the window beside the notes box, so the rail's scrolling can't clip it.
  const style = anchor
    ? { left: Math.min(anchor.right + 10, window.innerWidth - 416), bottom: Math.max(8, window.innerHeight - anchor.bottom) }
    : undefined;
  return (
    <div
      className="st-pop"
      style={style}
      role="dialog"
      aria-label="Today's notes"
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
          e.preventDefault();
          onSave(v.trim());
        }
      }}
    >
      <div className="st-row-between">
        <span className="st-pop-title">Today's notes</span>
        <span className="st-t3 st-xs">This shoot only · most specific</span>
      </div>
      <textarea className="st-textarea" aria-label="Today's notes" autoFocus value={v} maxLength={2000} onChange={(e) => setV(e.target.value)} />
      <span className="st-t3 st-xs">{hint}</span>
      <div className="st-row-8">
        <button type="button" className="st-btn st-btn-pri st-btn-s" onClick={() => onSave(v.trim())}>
          Done <span className="st-kbd">⌘↵</span>
        </button>
        <button type="button" className="st-btn st-btn-s" onClick={onClose}>
          Cancel <span className="st-mono st-t3">Esc</span>
        </button>
      </div>
    </div>
  );
}
