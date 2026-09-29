import { useState } from "react";
import { api, imageUrl } from "../api/client";
import type { Session } from "../api/types";
import { useApp } from "../AppContext";
import "./library.css";
import "./sessions.css";
import "./workflows.css";

type SessionRow = Session;

const STATUS: Record<string, { glyph: string; word: string }> = {
  active: { glyph: "●", word: "Active" },
  paused: { glyph: "‖", word: "Paused" },
  completed: { glyph: "✓", word: "Completed" },
};

function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (d.toDateString() === new Date().toDateString()) return "Today";
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

type GroupBy = "template" | "date";
const GROUP_KEY = "aperture-ally.sessions-group";

interface Group {
  id: string;
  title: string;
  meta: string;
  templateId: string | null;
  rows: SessionRow[];
}

/** How a shoot's shot list relates to its template, as the row tag. */
export function relationTag(s: SessionRow): { g: string; text: string; kind: "diff" | "saved" | "same" | "new" | "mock" | "none" } {
  if (s.assess_provider === "mock") return { g: "▦", text: "MOCK PROVIDER", kind: "mock" };
  if (s.simulated) return { g: "▦", text: "SIMULATED", kind: "mock" };
  const o = s.origin;
  if (o && o.changes > 0) return { g: "◆", text: `${o.changes} ${o.changes === 1 ? "shot" : "shots"} changed · not saved`, kind: "diff" };
  if (o?.saved?.as_new) return { g: "+", text: `Saved as new template: ${o.saved.name}`, kind: "new" };
  if (o?.saved) return { g: "↑", text: `Saved to template → v${o.saved.version}`, kind: "saved" };
  if (o?.template_name) return { g: "=", text: "Same as template", kind: "same" };
  return { g: "·", text: "Blank shot list", kind: "none" };
}

function groupSessions(rows: SessionRow[], by: GroupBy): Group[] {
  const map = new Map<string, Group>();
  for (const s of rows) {
    let id: string, title: string;
    if (by === "date") {
      id = shortDate(s.created_at);
      title = id;
    } else if (!s.project_id) {
      id = "none";
      title = "Before projects";
    } else {
      id = s.template_id ?? `p:${s.project_id}`;
      title = [s.origin?.project_name, s.origin?.template_name ?? "Blank shot list"].filter(Boolean).join(" › ");
    }
    const g = map.get(id) ?? { id, title, meta: "", templateId: by === "template" ? s.template_id ?? null : null, rows: [] };
    g.rows.push(s);
    map.set(id, g);
  }
  for (const g of map.values()) {
    const n = `${g.rows.length} ${g.rows.length === 1 ? "shoot" : "shoots"}`;
    const v = g.templateId ? g.rows[0].origin?.template_current_version : null;
    g.meta = v ? `v${v} · ${n}` : n;
  }
  return [...map.values()];
}

export function SessionsTab({
  sessions,
  onOpen,
  onNewShoot,
  onOpenTemplate,
}: {
  sessions: Session[];
  onOpen: (sid: string) => void;
  onNewShoot: () => void;
  onOpenTemplate: (templateId: string) => void;
}) {
  const { sid, state, run, refresh, refreshSessions } = useApp();
  const [by, setByState] = useState<GroupBy>(() => {
    try {
      return localStorage.getItem(GROUP_KEY) === "date" ? "date" : "template";
    } catch {
      return "template";
    }
  });
  const setBy = (v: GroupBy) => {
    try {
      localStorage.setItem(GROUP_KEY, v);
    } catch {
      /* ignore */
    }
    setByState(v);
    setFilter("all");
  };
  const [filter, setFilter] = useState("all");
  const rows = [...sessions].reverse() as SessionRow[];
  const allGroups = groupSessions(rows, "template");
  const groups = groupSessions(rows, by).map((g) => ({
    ...g,
    rows: filter === "all" ? g.rows : g.rows.filter((r) => (r.template_id ?? (r.project_id ? `p:${r.project_id}` : "none")) === filter),
  })).filter((g) => g.rows.length);
  const projectCount = new Set(sessions.map((s) => s.project_id).filter(Boolean)).size;

  const photos = (s: SessionRow) => (s.id === sid && state ? state.captures.length : s.capture_count);
  const keepers = (s: SessionRow) =>
    s.id === sid && state
      ? `${state.coverage.resolved} / ${state.coverage.total}`
      : s.keeper_count != null && s.shot_count != null
        ? `${s.keeper_count} / ${s.shot_count}`
        : "—";
  const filterLabel = (g: Group) => (g.id === "none" ? g.title : g.title.split(" › ").pop()!);

  return (
    <div className="wf-screen ses-screen">
      <div className="ses-head">
        <h2 className="ses-h1" id="sessions-h">
          Sessions
        </h2>
        <span className="lib-t3 lib-small">
          {sessions.length} {sessions.length === 1 ? "shoot" : "shoots"}
          {projectCount ? ` · ${projectCount} ${projectCount === 1 ? "project" : "projects"}` : ""} · stored on this Mac
        </span>
        <div className="ses-head-actions">
          <span className="lib-small lib-t2">Group by</span>
          <div className="ses-seg" role="radiogroup" aria-label="Group by">
            <button type="button" role="radio" aria-checked={by === "template"} onClick={() => setBy("template")}>
              Project › Template
            </button>
            <button type="button" role="radio" aria-checked={by === "date"} onClick={() => setBy("date")}>
              Date
            </button>
          </div>
          <button type="button" className="lib-btn lib-btn-pri lib-btn-s ses-new" onClick={onNewShoot}>
            New shoot <span className="lib-kbd">⌘N</span>
          </button>
        </div>
      </div>
      {allGroups.length > 1 && (
        <div className="ses-filters" role="group" aria-label="Filter">
          <button type="button" className="ses-chip" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>
            All · {sessions.length}
          </button>
          {allGroups.map((g) => (
            <button key={g.id} type="button" className="ses-chip" aria-pressed={filter === g.id} onClick={() => setFilter(g.id)}>
              {filterLabel(g)} · {g.rows.length}
            </button>
          ))}
        </div>
      )}
      {rows.length === 0 && (
        <div className="lib-empty ses-empty">
          <span className="lib-strong lib-body">No shoots yet</span>
          <span className="lib-small lib-t2">Start one from a template. It shows up here with its photos and keepers.</span>
          <div className="lib-row-8">
            <button type="button" className="lib-btn lib-btn-pri lib-btn-s" onClick={onNewShoot}>
              New shoot
            </button>
          </div>
        </div>
      )}
      {groups.map((g) => (
        <section key={g.id} className="ses-group" aria-label={g.title}>
          <div className="ses-group-head">
            <span className="lib-body lib-bold">{g.title}</span>
            <span className="lib-mono lib-xs lib-t3">{g.meta}</span>
            {g.templateId && (
              <button type="button" className="lib-btn-text lib-small ses-group-action" onClick={() => onOpenTemplate(g.templateId!)}>
                Open template
              </button>
            )}
          </div>
          {g.rows.map((s) => {
            const tag = relationTag(s);
            const st = STATUS[s.status] ?? { glyph: "·", word: s.status };
            const cover = s.cover_capture_id;
            return (
              <div key={s.id} className={s.id === sid ? "ses-row is-current" : "ses-row"}>
                {cover ? <img className="ses-thumb" src={imageUrl(cover, "thumb")} alt="" loading="lazy" /> : <div className="ses-thumb ses-thumb-empty" aria-hidden="true" />}
                <span className="lib-stack-2 lib-minw0">
                  <button type="button" className="ses-open" onClick={() => onOpen(s.id)}>
                    {s.name}
                    <span className="sr-only"> — open</span>
                  </button>
                  <span className="lib-xs lib-t3 lib-ellipsis">
                    {[s.shoot_preferences || s.product || "—", s.status === "active" ? "in progress" : s.status !== "completed" ? st.word.toLowerCase() : null, s.id === sid ? "open now" : null]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
                <span className="lib-small lib-t2">{shortDate(s.created_at)}</span>
                <span className="lib-mono lib-small" title="Photos">{photos(s) ?? "—"}</span>
                <span className="lib-mono lib-small" title="Keepers">{keepers(s)}</span>
                <span className="ses-tag-cell">
                  <span className={`ses-tag ses-tag-${tag.kind}`}>
                    <span className="lib-mono">{tag.g}</span> {tag.text}
                  </span>
                  {s.status !== "active" && (
                    <button
                      type="button"
                      className="lib-btn-text lib-xs"
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
        </section>
      ))}
      <p className="lib-t3 lib-xs">Only the active shoot's watch folder is watched; starting or activating a shoot pauses the others.</p>
      {state && sid && <ImportPhotos sid={sid} />}
    </div>
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
