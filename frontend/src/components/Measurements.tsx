import { useRef, useState } from "react";
import { imageUrl } from "../api/client";
import type { Capture, ZoneName } from "../api/types";
import { contextLine, type ScopeRow, WHOLE } from "../lib/inspector";
import { Histogram, ZONES } from "../ui/Histogram";
import { SEVERITY } from "../ui/status";
import { useDismiss } from "./ShootStatus";

const MUTED_SEV = { glyph: "–", word: "Not measured", color: "var(--t3)", tint: "var(--raised)" };

/** Caption and swatch for a zone shown on the photo. */
export const ZONE_CAPTION: Record<ZoneName, { caption: string; swatch: string }> = {
  clip_low: { caption: "Solid blue = pure black, no detail", swatch: "var(--lost-lo)" },
  shadows: { caption: "Shadows", swatch: "color-mix(in oklch, var(--acc) 35%, transparent)" },
  midtones: { caption: "Mid-tones", swatch: "color-mix(in oklch, var(--acc) 25%, transparent)" },
  highlights: { caption: "Highlights", swatch: "color-mix(in oklch, var(--acc) 30%, transparent)" },
  clip_high: { caption: "Solid red = pure white, no detail", swatch: "var(--lost-hi)" },
};

function RegionTile({ capture, row }: { capture: Capture; row: ScopeRow }) {
  const [failed, setFailed] = useState(false);
  const hasCrop = row.key !== WHOLE && capture.evidence.crops.some((c) => c.id === row.key);
  return (
    <span className="insp-tile" aria-hidden="true">
      {hasCrop && !failed ? (
        <img src={`${imageUrl(capture.id, `crop_${row.key}`)}?v=${capture.evidence.crops.map((c) => c.id).join("-")}`} alt="" loading="lazy" onError={() => setFailed(true)} />
      ) : null}
      <span className="insp-tile-tag mono">{row.key === WHOLE ? "all" : row.index ?? "·"}</span>
    </span>
  );
}

/**
 * Brightness inspector under the stage: marked regions first, whole frame last; a plain-language
 * headline from the backend reading, and the histogram whose zones light up on the photo.
 */
export function BrightnessInspector({
  capture,
  rows,
  scope,
  pinnedScope,
  onHoverScope,
  onPinScope,
  zone,
  pinnedZone,
  onHoverZone,
  onPinZone,
}: {
  capture: Capture;
  rows: ScopeRow[];
  scope: string;
  pinnedScope: string;
  onHoverScope: (k: string | null) => void;
  onPinScope: (k: string) => void;
  zone: ZoneName | null;
  pinnedZone: ZoneName | null;
  onHoverZone: (z: ZoneName | null) => void;
  onPinZone: (z: ZoneName) => void;
}) {
  const [help, setHelp] = useState(false);
  const helpWrap = useRef<HTMLDivElement>(null);
  const helpBtn = useRef<HTMLButtonElement>(null);
  useDismiss(help, () => setHelp(false), helpWrap, helpBtn);
  const row = rows.find((r) => r.key === scope) ?? rows[rows.length - 1];
  const ins = capture.histogram_insights;
  const measured = rows.some((r) => r.bins || r.insight);

  if (!measured) {
    return (
      <section className="inspector is-empty" aria-label="Brightness">
        <p className="muted small">The brightness reading appears once the photo has been measured.</p>
      </section>
    );
  }

  const sev = row.insight ? SEVERITY[row.insight.severity] : MUTED_SEV;
  const headline = row.insight?.headline ?? (row.bins ? "Measured" : "Not measured yet");
  const clipButton = (z: "clip_low" | "clip_high", text: string) => (
    <button
      type="button"
      className={`insp-lost${zone === z ? " is-on" : ""}`}
      aria-pressed={pinnedZone === z}
      onMouseEnter={() => onHoverZone(z)}
      onMouseLeave={() => onHoverZone(null)}
      onFocus={() => onHoverZone(z)}
      onBlur={() => onHoverZone(null)}
      onClick={() => onPinZone(z)}
    >
      {z === "clip_low" && <span className="swatch" style={{ background: "var(--lost-lo)" }} />}
      {text}
      {z === "clip_high" && <span className="swatch" style={{ background: "var(--lost-hi)" }} />}
    </button>
  );

  return (
    <section className="inspector" aria-label="Brightness">
      <div className="insp-list">
        <span className="label-caps insp-list-h">Marked regions first</span>
        {rows.map((r) => {
          const s = r.insight ? SEVERITY[r.insight.severity] : MUTED_SEV;
          return (
            <button
              key={r.key}
              type="button"
              className={`insp-row${r.key === scope ? " is-on" : ""}`}
              aria-pressed={r.key === pinnedScope}
              onMouseEnter={() => onHoverScope(r.key)}
              onMouseLeave={() => onHoverScope(null)}
              onClick={() => onPinScope(r.key)}
            >
              <RegionTile capture={capture} row={r} />
              <span className="insp-row-text">
                <span className="insp-row-name">{r.name}</span>
                <span className="insp-row-meta mono">{r.meta}</span>
              </span>
              <span className="glyph" style={{ color: s.color }} aria-hidden="true">
                {s.glyph}
              </span>
              <span className="sr-only">{s.word}</span>
            </button>
          );
        })}
      </div>
      <div className="insp-main">
        <div className="insp-head" aria-live="polite">
          <span className="insp-sev glyph" style={{ background: sev.tint, color: sev.color }} aria-hidden="true">
            {sev.glyph}
          </span>
          <span className="insp-head-text">
            <span className="insp-headline" style={{ color: row.insight?.severity === "problem" ? "var(--ret)" : undefined }}>
              <span className="insp-who">{row.name} · </span>
              <span className="sr-only">{sev.word}: </span>
              {headline}
            </span>
            <span className="insp-context">{contextLine(row.insight)}</span>
          </span>
        </div>
        <div className="insp-plot">
          <div className="insp-legend">
            {clipButton("clip_low", "pure black")}
            {clipButton("clip_high", "pure white")}
          </div>
          {row.bins ? (
            <Histogram
              bins={row.bins}
              clipHigh={row.clipHigh}
              clipLow={row.clipLow}
              activeZone={zone}
              height={50}
              labels={false}
              label={`Brightness of ${row.name}`}
              onZoneEnter={onHoverZone}
              onZoneLeave={() => onHoverZone(null)}
              onZoneClick={onPinZone}
            />
          ) : (
            <div className="insp-nobins small muted">No histogram for this region yet. It is measured on the next photo.</div>
          )}
          <div className="insp-zones" role="group" aria-label="Show a brightness zone on the photo">
            <span />
            {ZONES.filter((z) => z.short).map((z) => (
              <button
                key={z.id}
                type="button"
                className={zone === z.id ? "is-on" : undefined}
                aria-pressed={pinnedZone === z.id}
                onMouseEnter={() => onHoverZone(z.id)}
                onMouseLeave={() => onHoverZone(null)}
                onFocus={() => onHoverZone(z.id)}
                onBlur={() => onHoverZone(null)}
                onClick={() => onPinZone(z.id)}
              >
                {z.short}
              </button>
            ))}
            <span />
          </div>
        </div>
        <div className="insp-foot">
          <div className="insp-help-wrap" ref={helpWrap}>
            <button ref={helpBtn} type="button" className="btn-text" aria-expanded={help} onClick={() => setHelp((h) => !h)}>
              How to read this {help ? "▾" : "▸"}
            </button>
            {help && (
              <div className="popover insp-help" role="dialog" aria-label="How to read the brightness graph">
                <h3>How to read the brightness graph</h3>
                <ul>
                  {(ins?.how_to_read ?? FALLBACK_HOW_TO).map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <span>Hover a zone → see it on the photo</span>
          <span className="insp-caveat" title={`${ins?.caveat ?? "Measured on the processed JPEG, not the RAW file."} RAW may hold more highlight detail.`}>
            From JPEG, not RAW — RAW may hold more detail
          </span>
        </div>
      </div>
    </section>
  );
}

const FALLBACK_HOW_TO = [
  "Left to right is dark to bright. The taller a bar, the more of the picture has that brightness.",
  "A spike at either edge means pure black (blue on the photo) or pure white (red). There's no detail left there.",
  "No shape is “correct”. What matters is whether the part you care about is lost.",
];
