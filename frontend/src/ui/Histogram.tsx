// Brightness histogram in the design-system style: bars on a zoned ground, with the two
// "no detail" walls (pure black left, pure white right) drawn in the lost-detail colours.
// Zones follow the backend rules (imaging/interpret.py): shadows < 64, highlights >= 192 of 255.
import type { ZoneName } from "../api/types";

export const ZONES: { id: ZoneName; label: string; short: string }[] = [
  { id: "clip_low", label: "Pure black: no detail", short: "" },
  { id: "shadows", label: "Shadows", short: "Shadows" },
  { id: "midtones", label: "Mid-tones", short: "Mid-tones" },
  { id: "highlights", label: "Highlights", short: "Highlights" },
  { id: "clip_high", label: "Pure white: no detail", short: "" },
];

/** Zone of a bin index for an n-bin 0..255 histogram. */
export function zoneOfBin(i: number, n: number): Exclude<ZoneName, "clip_low" | "clip_high"> {
  const v = ((i + 0.5) / n) * 256;
  return v < 64 ? "shadows" : v < 192 ? "midtones" : "highlights";
}

/** Clip fraction at/above which the wall is drawn in the lost-detail colour (matches CLIP_WARN). */
export const CLIP_SHOW = 0.002;

export interface HistogramProps {
  bins: number[];
  /** Fractions of pixels at pure white / pure black (0..1). Drives the wall heights. */
  clipHigh?: number;
  clipLow?: number;
  /** Highlight one zone (hover/pin); other bars stay idle. */
  activeZone?: ZoneName | null;
  /** Previous capture's bins, drawn as an outline over the current bars (before/after). */
  previous?: number[] | null;
  height?: number;
  /** Zone labels under the plot. */
  labels?: boolean;
  onZoneEnter?: (z: ZoneName) => void;
  onZoneLeave?: () => void;
  onZoneClick?: (z: ZoneName) => void;
  label?: string;
  className?: string;
}

const pctText = (f: number) => `${(f * 100).toFixed(f < 0.1 ? 1 : 0)}%`;

export function Histogram({
  bins,
  clipHigh = 0,
  clipLow = 0,
  activeZone = null,
  previous = null,
  height = 96,
  labels = true,
  onZoneEnter,
  onZoneLeave,
  onZoneClick,
  label = "Brightness histogram",
  className = "",
}: HistogramProps) {
  const n = bins.length || 1;
  const max = Math.max(...bins, ...(previous ?? []), 1e-9);
  const wallH = (f: number) => (f <= 0 ? 0 : Math.min(100, 8 + Math.sqrt(f) * 140));
  const barColor = (i: number) => {
    const z = zoneOfBin(i, n);
    if (activeZone === z) return "var(--acc)";
    return previous ? "color-mix(in oklch, var(--acc) 60%, transparent)" : "var(--bar-idle)";
  };
  const interactive = Boolean(onZoneEnter || onZoneClick);
  const prevPoints = previous
    ? previous.map((b, i) => `${((i + 0.5) / previous.length) * 100},${100 - (b / max) * 96}`).join(" ")
    : null;
  return (
    <div className={`hist ${className}`} role="img" aria-label={`${label}: dark on the left, bright on the right. Pure black ${pctText(clipLow)}, pure white ${pctText(clipHigh)}.`}>
      <div className="hist-plot" style={{ height }}>
        <div className="hist-zones" aria-hidden="true">
          {ZONES.map((z) => (
            <div
              key={z.id}
              className={`hist-zone hist-zone-${z.id}${activeZone === z.id ? " is-active" : ""}`}
              onMouseEnter={onZoneEnter ? () => onZoneEnter(z.id) : undefined}
              onMouseLeave={onZoneLeave}
              onClick={onZoneClick ? () => onZoneClick(z.id) : undefined}
              title={interactive ? z.label : undefined}
            />
          ))}
        </div>
        <div className="hist-wall hist-wall-lo" aria-hidden="true"
          style={{ height: `${wallH(clipLow)}%`, background: clipLow >= CLIP_SHOW || activeZone === "clip_low" ? "var(--lost-lo)" : "var(--bar-idle)" }} />
        <div className="hist-bars" aria-hidden="true">
          {bins.map((b, i) => (
            <span key={i} style={{ height: `${Math.max(1, (b / max) * 96)}%`, background: barColor(i) }} />
          ))}
        </div>
        <div className="hist-wall hist-wall-hi" aria-hidden="true"
          style={{ height: `${wallH(clipHigh)}%`, background: clipHigh >= CLIP_SHOW || activeZone === "clip_high" ? "var(--lost-hi)" : "var(--bar-idle)" }} />
        {prevPoints && (
          <svg className="hist-prev" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <polyline points={prevPoints} fill="none" stroke="var(--t2)" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
          </svg>
        )}
      </div>
      {labels && (
        <div className="hist-labels" aria-hidden="true">
          <span />
          <span>Shadows</span>
          <span>Mid-tones</span>
          <span>Highlights</span>
          <span />
        </div>
      )}
    </div>
  );
}
