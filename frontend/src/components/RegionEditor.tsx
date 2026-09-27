import { type ReactNode, useEffect, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { api } from "../api/client";
import type { Region, Shot } from "../api/types";
import { useApp } from "../AppContext";
import { isTypingTarget } from "../lib/keys";
import { addRegion, MAX_REGIONS, normalizeDrag, type NormRect, type Point, removeRegion, renameRegion } from "../lib/regions";

/**
 * The photo on the stage with the shot's sharp regions (up to 3). Drag on the photo to draw one, click a
 * rect to select it, click its label to rename, Backspace/Delete removes the selected one. Regions are
 * saved on the shot, so the next photo is measured in the same places. `children` are overlays drawn
 * inside the photo frame (zone patches, captions).
 */
export function RegionEditor({
  src,
  alt,
  shot,
  aspect,
  onNaturalSize,
  activeRegionId = null,
  onHoverRegion,
  onPickRegion,
  children,
}: {
  src: string;
  alt: string;
  shot: Shot | null;
  /** Width / height of the image, so the frame fits the stage before the image has loaded. */
  aspect: number;
  onNaturalSize?: (w: number, h: number) => void;
  activeRegionId?: string | null;
  onHoverRegion?: (id: string | null) => void;
  onPickRegion?: (id: string) => void;
  children?: ReactNode;
}) {
  const { sid, run, refresh, toast } = useApp();
  const frameRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [drag, setDrag] = useState<{ start: Point; end: Point } | null>(null);
  const [optimistic, setOptimistic] = useState<Region[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; text: string } | null>(null);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  // The server copy wins once it changes (after our save, or an edit elsewhere).
  useEffect(() => setOptimistic(null), [shot?.id, shot?.updated_at]);
  useEffect(() => {
    setFailed(false);
    setLoaded(false);
  }, [src]);

  const regions = optimistic ?? shot?.sharp_regions ?? [];
  const full = regions.length >= MAX_REGIONS;

  const save = (next: Region[], label: string) => {
    if (!sid || !shot) return;
    setOptimistic(next);
    void run(label, async () => {
      await api.patchShot(sid, shot.id, { sharp_regions: next });
      await refresh();
      return true;
    }).then((ok) => {
      if (!ok) setOptimistic(null);
    });
  };

  const del = (id: string) => {
    save(removeRegion(regions, id), "Delete region");
    setSelected(null);
    setRenaming(null);
    toast({ glyph: "✓", text: "Region deleted" });
  };

  const commitRename = () => {
    if (!renaming) return;
    const r = regions.find((x) => x.id === renaming.id);
    const text = renaming.text.trim();
    setRenaming(null);
    if (r && text && text !== r.label) save(renameRegion(regions, r.id, text), "Rename region");
  };

  // Backspace / Delete removes the selected region; Esc deselects. Never while typing.
  // Capture phase: while a region is selected, Esc only deselects (not cancel analysis/speech too).
  useEffect(() => {
    if (!selected || renaming) return;
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "Backspace" || e.key === "Delete") {
        e.preventDefault();
        del(selected);
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopImmediatePropagation();
        setSelected(null);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  const rel = (e: { clientX: number; clientY: number }): Point => {
    const r = frameRef.current!.getBoundingClientRect();
    return { x: Math.min(Math.max(e.clientX - r.left, 0), r.width), y: Math.min(Math.max(e.clientY - r.top, 0), r.height) };
  };
  const frameSize = () => {
    const r = frameRef.current!.getBoundingClientRect();
    return { width: r.width, height: r.height };
  };

  const onPointerDown = (e: RPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || !frameRef.current) return;
    if ((e.target as HTMLElement).closest(".region-rect, .stage-control")) return;
    setSelected(null);
    if (renaming) commitRename();
    if (!shot || failed) return;
    if (full) {
      toast({ glyph: "!", text: `${MAX_REGIONS} regions max. Delete one first`, tone: "unc" });
      return;
    }
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const p = rel(e);
    setDrag({ start: p, end: p });
  };

  const finish = () => {
    if (!drag || !frameRef.current) return;
    const img = imgRef.current;
    const size = frameSize();
    const rect = normalizeDrag(drag.start, drag.end, size, {
      width: img?.naturalWidth || size.width,
      height: img?.naturalHeight || size.height,
    });
    setDrag(null);
    if (!rect) return;
    const next = addRegion(regions, rect);
    if (!next) return;
    const added = next[next.length - 1];
    save(next, "Save sharp regions");
    setSelected(added.id);
    setRenaming({ id: added.id, text: added.label });
  };

  let ghost: (NormRect & { label: string }) | null = null;
  if (drag && frameRef.current) {
    const size = frameSize();
    const r = normalizeDrag(drag.start, drag.end, size, undefined, 0);
    if (r && (r.w > 0 || r.h > 0)) ghost = { ...r, label: `New region · ${Math.round(r.w * 100)} × ${Math.round(r.h * 100)}%` };
  }

  const box = (r: NormRect) => ({ left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` });
  const hint = !shot
    ? "Assign this photo to a shot to mark regions"
    : full
      ? `${MAX_REGIONS} of ${MAX_REGIONS} regions · select one and press ⌫ to delete`
      : `Drag to draw · ${regions.length} of ${MAX_REGIONS} used · click a label to rename`;

  return (
    <div
      ref={frameRef}
      className={`photo-frame${shot && !full ? " can-draw" : ""}${selected ? " has-selection" : ""}${drag ? " is-drawing" : ""}`}
      style={{ ["--ar" as string]: String(aspect) }}
      onPointerDown={onPointerDown}
      onPointerMove={(e) => drag && setDrag({ ...drag, end: rel(e) })}
      onPointerUp={finish}
      onPointerCancel={() => setDrag(null)}
      data-testid="photo-frame"
    >
      {failed ? (
        <div className="photo-missing">Preview not available yet.</div>
      ) : (
        <img
          ref={imgRef}
          src={src}
          alt={alt}
          draggable={false}
          className={loaded ? "photo is-loaded" : "photo"}
          onLoad={(e) => {
            setLoaded(true);
            const i = e.currentTarget;
            if (i.naturalWidth && i.naturalHeight) onNaturalSize?.(i.naturalWidth, i.naturalHeight);
          }}
          onError={() => setFailed(true)}
        />
      )}
      {children}
      {regions.map((r, i) => {
        const isSel = r.id === selected;
        const on = isSel || r.id === activeRegionId;
        const isRen = renaming?.id === r.id;
        return (
          <div
            key={r.id}
            className={`region-rect${on ? " is-active" : ""}`}
            style={box(r)}
            onPointerEnter={() => onHoverRegion?.(r.id)}
            onPointerLeave={() => onHoverRegion?.(null)}
            onPointerDown={(e) => {
              if (e.button !== 0) return;
              e.stopPropagation();
              setSelected(r.id);
              onPickRegion?.(r.id);
            }}
          >
            {isRen ? (
              <input
                className="region-rename"
                aria-label={`Name for region ${i + 1}`}
                autoFocus
                value={renaming.text}
                maxLength={60}
                onChange={(e) => setRenaming({ id: r.id, text: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename();
                  if (e.key === "Escape") {
                    e.stopPropagation();
                    setRenaming(null);
                  }
                }}
                onBlur={commitRename}
                onPointerDown={(e) => e.stopPropagation()}
              />
            ) : (
              <button
                type="button"
                className="region-label"
                title="Click to rename"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => {
                  setSelected(r.id);
                  setRenaming({ id: r.id, text: r.label });
                }}
              >
                {i + 1} {r.label}
              </button>
            )}
            {isSel && !isRen && (
              <div className="region-tools" onPointerDown={(e) => e.stopPropagation()}>
                <button type="button" onClick={() => setRenaming({ id: r.id, text: r.label })}>
                  Rename
                </button>
                <button type="button" className="danger" aria-keyshortcuts="Backspace Delete" onClick={() => del(r.id)}>
                  Delete <span className="kbd">⌫</span>
                </button>
              </div>
            )}
          </div>
        );
      })}
      {ghost && (
        <div className="region-ghost" style={box(ghost)} aria-hidden="true">
          <span>{ghost.label}</span>
        </div>
      )}
      <div className="stage-tag region-hint" aria-live="polite">
        {hint}
      </div>
    </div>
  );
}
