import { useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { api } from "../api/client";
import type { Region, Shot } from "../api/types";
import { useApp } from "../AppContext";
import { MAX_REGIONS, nextRegionId, normalizeDrag, type NormRect, type Point } from "../lib/regions";

/**
 * Overview image with the shot's sharp-region overlays. Click-drag to draw a new region (max 3);
 * the region is normalized to the image's natural size and saved on the shot.
 */
export function RegionEditor({
  src,
  alt,
  shot,
  overlaySrc = null,
}: {
  src: string;
  alt: string;
  shot: Shot | null;
  overlaySrc?: string | null;
}) {
  const { sid, run, refresh } = useApp();
  const imgRef = useRef<HTMLImageElement>(null);
  const [drag, setDrag] = useState<{ start: Point; end: Point } | null>(null);
  const [pending, setPending] = useState<NormRect | null>(null);
  const [label, setLabel] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const regions = shot?.sharp_regions ?? [];
  const canDraw = !!shot && regions.length < MAX_REGIONS && !pending;

  const rel = (e: RPointerEvent): Point => {
    const r = imgRef.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  const finish = () => {
    if (!drag || !imgRef.current) return;
    const img = imgRef.current;
    const r = img.getBoundingClientRect();
    const rect = normalizeDrag(
      drag.start,
      drag.end,
      { width: r.width, height: r.height },
      { width: img.naturalWidth || r.width, height: img.naturalHeight || r.height },
    );
    setDrag(null);
    if (rect) {
      setPending(rect);
      setLabel("");
    }
  };

  const saveRegions = (next: Region[]) =>
    run("Save sharp regions", async () => {
      if (!sid || !shot) return;
      await api.patchShot(sid, shot.id, { sharp_regions: next });
      await refresh();
    });

  const addPending = async () => {
    if (!pending || !shot) return;
    const id = nextRegionId(regions);
    if (!id) return;
    await saveRegions([...regions, { id, label: label.trim() || id, ...pending }]);
    setPending(null);
  };

  const box = (r: NormRect) => ({
    left: `${r.x * 100}%`,
    top: `${r.y * 100}%`,
    width: `${r.w * 100}%`,
    height: `${r.h * 100}%`,
  });

  let dragRect: NormRect | null = null;
  if (drag && imgRef.current) {
    const r = imgRef.current.getBoundingClientRect();
    dragRect = normalizeDrag(drag.start, drag.end, { width: r.width, height: r.height }, undefined, 0);
  }

  return (
    <div className="region-editor">
      <div
        className={canDraw ? "overview-wrap drawable" : "overview-wrap"}
        onPointerDown={(e) => {
          if (!canDraw || !loaded || e.button !== 0) return;
          e.preventDefault();
          (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
          const p = rel(e);
          setDrag({ start: p, end: p });
        }}
        onPointerMove={(e) => drag && setDrag({ ...drag, end: rel(e) })}
        onPointerUp={finish}
        onPointerCancel={() => setDrag(null)}
      >
        {failed ? (
          <div className="img-missing">Overview not available yet.</div>
        ) : (
          <img
            ref={imgRef}
            src={src}
            alt={alt}
            draggable={false}
            onLoad={() => {
              setLoaded(true);
              setFailed(false);
            }}
            onError={() => setFailed(true)}
          />
        )}
        {loaded && overlaySrc && <img className="clip-overlay" src={overlaySrc} alt="" aria-hidden="true" draggable={false} />}
        {loaded &&
          regions.map((r) => (
            <div key={r.id} className="region-box" style={box(r)}>
              <span className="region-tag">
                {r.id}: {r.label}
              </span>
            </div>
          ))}
        {pending && <div className="region-box region-pending" style={box(pending)} />}
        {dragRect && <div className="region-box region-drawing" style={box(dragRect)} />}
      </div>

      {shot && (
        <div className="region-controls">
          <p className="small">
            Sharp regions for <strong>{shot.title}</strong> ({regions.length}/{MAX_REGIONS}).{" "}
            {canDraw ? "Click and drag on the photo to add one." : regions.length >= MAX_REGIONS ? "Delete one to add another." : ""}
          </p>
          {pending && (
            <form
              className="inline-form"
              onSubmit={(e) => {
                e.preventDefault();
                void addPending();
              }}
            >
              <label>
                Label for new region
                <input autoFocus value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. toe box logo" />
              </label>
              <button type="submit" className="primary">
                Add region
              </button>
              <button type="button" onClick={() => setPending(null)}>
                Cancel
              </button>
            </form>
          )}
          {regions.length > 0 && (
            <ul className="region-list">
              {regions.map((r) => (
                <li key={r.id}>
                  {r.id}: {r.label}{" "}
                  <button
                    type="button"
                    aria-label={`Delete region ${r.id} ${r.label}`}
                    onClick={() => void saveRegions(regions.filter((x) => x.id !== r.id))}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="small muted">Crops are made when a photo is analysed; use “Review again” to refresh crops after changing regions.</p>
        </div>
      )}
    </div>
  );
}
