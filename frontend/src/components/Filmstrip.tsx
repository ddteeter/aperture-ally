import { useEffect, useRef, useState } from "react";
import { api, imageUrl } from "../api/client";
import type { Capture, PendingFile } from "../api/types";
import { useApp } from "../AppContext";
import { activeKeeperIds, captureBadge, captureTag, type FilmFilter, pendingMeta } from "../lib/filmstrip";
import { shotTitle } from "../lib/format";
import { useDismiss } from "./ShootStatus";

const FILTERS: { id: FilmFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "shot", label: "This shot" },
  { id: "keepers", label: "Keepers" },
];

/** 92 px strip under the stage: 64×48 thumbs with a glyph badge, oldest left, newest right. */
export function Filmstrip({
  captures,
  total,
  filter,
  onFilter,
  selectedId,
  onSelect,
}: {
  /** Captures to show (already filtered and ordered). */
  captures: Capture[];
  total: number;
  filter: FilmFilter;
  onFilter: (f: FilmFilter) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { state } = useApp();
  const listRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(".film-thumb.is-selected");
    el?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [selectedId, captures.length]);
  if (!state) return null;
  const keepers = activeKeeperIds(state.keepers);
  const pending = filter === "keepers" ? [] : state.pending_files;
  const empty = captures.length === 0 && pending.length === 0;

  return (
    <section className="filmstrip" aria-labelledby="film-h">
      <div className="film-head">
        <h2 id="film-h" className="label-caps">
          Filmstrip
        </h2>
        <div className="film-filters" role="group" aria-label="Filter photos">
          {FILTERS.map((f) => (
            <button key={f.id} type="button" aria-pressed={filter === f.id} onClick={() => onFilter(f.id)}>
              {f.label}
              {f.id === "all" ? ` ${total}` : ""}
            </button>
          ))}
        </div>
        <span className="film-keys mono" aria-hidden="true">
          ← → step
        </span>
      </div>
      {empty ? (
        <div className="film-empty">
          {total === 0
            ? "No photos yet. They appear here as files land in the watch folder."
            : filter === "keepers"
              ? "No keepers yet. Accept one from the coach panel."
              : "No photos for this shot yet."}
        </div>
      ) : (
        <ol className="film" ref={listRef} aria-keyshortcuts="ArrowLeft ArrowRight">
          {captures.map((c) => (
            <FilmThumb key={c.id} c={c} keeper={keepers.has(c.id)} selected={c.id === selectedId} onSelect={() => onSelect(c.id)} />
          ))}
          {pending.map((p) => (
            <PendingThumb key={p.key ?? p.name} p={p} />
          ))}
        </ol>
      )}
    </section>
  );
}

function FilmThumb({ c, keeper, selected, onSelect }: { c: Capture; keeper: boolean; selected: boolean; onSelect: () => void }) {
  const { state } = useApp();
  const [thumbFailed, setThumbFailed] = useState(false);
  const badge = captureBadge(c, keeper);
  const tag = captureTag(c);
  const shot = state ? shotTitle(state.shots, c.shot_id) : "";
  const label = `#${c.seq} · ${badge.word}${tag ? ` · ${tag.label}` : ""}`;
  return (
    <li data-testid={`film-${c.seq}`}>
      <button
        type="button"
        className={selected ? "film-thumb is-selected" : "film-thumb"}
        aria-pressed={selected}
        aria-label={`Photo #${c.seq}, ${shot}: ${badge.word}${tag ? `, ${tag.label}` : ""}`}
        title={`${label} · ${shot}`}
        onClick={onSelect}
      >
        {!thumbFailed && c.evidence.available ? (
          <img src={imageUrl(c.id, "thumb") + "?v=1"} alt="" loading="lazy" draggable={false} onError={() => setThumbFailed(true)} />
        ) : (
          <span className="film-ph" aria-hidden="true" />
        )}
        <span className="film-n mono" aria-hidden="true">{c.seq}</span>
        <span className="film-badge glyph" style={{ color: badge.color }} aria-hidden="true">
          {badge.glyph}
        </span>
        {tag && (
          <span className="film-tag mono" aria-hidden="true">
            {tag.text}
          </span>
        )}
      </button>
    </li>
  );
}

/** A watch-folder file that isn't a capture yet. Failed ones offer Read again / Skip. */
function PendingThumb({ p }: { p: PendingFile }) {
  const { sid, run, refresh } = useApp();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLLIElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  useDismiss(open, () => setOpen(false), wrap, btn);
  const meta = pendingMeta(p);
  const failed = p.status === "failed";
  const title = `${p.name} · ${meta.word}${p.note ? ` · ${p.note}` : ""}`;
  const act = (label: string, fn: (sid: string, key: string) => Promise<unknown>) => {
    setOpen(false);
    if (!sid || !p.key) return;
    void run(label, async () => {
      await fn(sid, p.key);
      await refresh();
    });
  };
  const body = (
    <>
      <span className="film-ph" aria-hidden="true" />
      <span className="film-badge glyph" style={{ color: meta.color }} aria-hidden="true">
        {meta.glyph}
      </span>
      {!failed && (
        <span className="film-writing mono" aria-hidden="true">
          writing
        </span>
      )}
    </>
  );
  return (
    <li className="film-pending" ref={wrap} data-testid={`pending-${p.name}`}>
      {failed ? (
        <button ref={btn} type="button" className="film-thumb is-pending" aria-label={title} title={title} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {body}
        </button>
      ) : (
        <span className="film-thumb is-pending" role="img" aria-label={title} title={title}>
          {body}
        </span>
      )}
      {open && (
        <div className="popover film-menu" role="dialog" aria-label={`${p.name} couldn’t be read`}>
          <span className="small">
            <b>{p.name}</b> couldn’t be read{p.note ? `: ${p.note}` : "."}
          </span>
          <div className="button-row">
            <button type="button" disabled={!p.key} onClick={() => act("Read again", api.pendingRetry)}>
              Read again
            </button>
            <button type="button" className="btn-text" disabled={!p.key} onClick={() => act("Skip file", api.pendingSkip)}>
              Skip file
            </button>
          </div>
        </div>
      )}
    </li>
  );
}
