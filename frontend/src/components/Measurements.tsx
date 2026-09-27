import type { HistogramInsights, InsightSeverity, Measurements as M, ScopeInsight } from "../api/types";
import { num, pct } from "../lib/format";

const SEVERITY_LABEL: Record<InsightSeverity, string> = {
  problem: "Detail lost",
  warn: "Check",
  info: "Note",
  ok: "OK",
};

/**
 * Luminance histogram with its reading aids drawn on: zone labels (shadows / mid-tones / highlights) and
 * the clipped edges. `clipHigh` / `clipLow` (fractions) light up the edge walls so "pressed against the
 * wall" is visible rather than implied.
 */
export function Histogram({
  bins,
  title = "Brightness histogram",
  clipHigh = 0,
  clipLow = 0,
  width = 256,
  height = 72,
}: {
  bins: number[];
  title?: string;
  clipHigh?: number;
  clipLow?: number;
  width?: number;
  height?: number;
}) {
  const w = width;
  const plotH = height - 14;
  const max = Math.max(...bins, 1e-9);
  const bw = w / Math.max(bins.length, 1);
  const q = w / 4;
  const edge = (f: number) => (f >= 0.02 ? "hist-edge hist-edge-problem" : f >= 0.002 ? "hist-edge hist-edge-warn" : "");
  return (
    <svg
      className="histogram"
      viewBox={`0 0 ${w} ${height}`}
      width={w}
      height={height}
      role="img"
      aria-label={`${title}: dark on the left, bright on the right. Pure black ${pct(clipLow)}, pure white ${pct(clipHigh)}.`}
    >
      <title>{title}</title>
      <rect x={0} y={0} width={w} height={plotH} className="hist-bg" />
      <rect x={0} y={0} width={q} height={plotH} className="hist-zone" />
      <rect x={3 * q} y={0} width={q} height={plotH} className="hist-zone" />
      {bins.map((b, i) => {
        const bh = (b / max) * (plotH - 2);
        return <rect key={i} x={i * bw} y={plotH - bh} width={Math.max(bw - 0.5, 0.5)} height={bh} className="hist-bar" />;
      })}
      {edge(clipLow) && <rect x={0} y={0} width={3} height={plotH} className={edge(clipLow)} />}
      {edge(clipHigh) && <rect x={w - 3} y={0} width={3} height={plotH} className={edge(clipHigh)} />}
      <text x={q / 2} y={height - 3} className="hist-label" textAnchor="middle">shadows</text>
      <text x={w / 2} y={height - 3} className="hist-label" textAnchor="middle">mid-tones</text>
      <text x={w - q / 2} y={height - 3} className="hist-label" textAnchor="middle">highlights</text>
    </svg>
  );
}

function ScopeReading({ s, bins }: { s: ScopeInsight; bins?: number[] }) {
  return (
    <div className={`insight insight-${s.severity}`}>
      <p className="insight-head">
        <span className={`chip chip-${s.severity}`}>{SEVERITY_LABEL[s.severity]}</span>{" "}
        <strong>{s.scope}</strong>: {s.headline}
      </p>
      {bins && bins.length > 0 && (
        <Histogram bins={bins} title={`Histogram of ${s.scope}`} clipHigh={s.highlight_clip} clipLow={s.shadow_clip} width={200} height={60} />
      )}
      <ul className="insight-findings">
        {s.findings.map((f, i) => (
          <li key={i}>
            <span className="small">
              <strong>{f.headline}.</strong> {f.detail}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** "What is the histogram saying?" — plain-language reading first, the numbers second. */
export function HistogramReading({
  insights,
  m,
  changes,
}: {
  insights: HistogramInsights;
  m: M;
  changes?: { baseline_seq: number; changes: string[] };
}) {
  return (
    <section className="histogram-reading" aria-label="What the histogram says">
      <p className="insight-summary" aria-live="polite">
        <strong>{insights.summary}</strong>
      </p>
      {changes && changes.changes.length > 0 && (
        <div className="insight-changes">
          <p className="small">
            <strong>What your retake changed</strong> (vs photo #{changes.baseline_seq}):
          </p>
          <ul className="small">
            {changes.changes.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}
      {insights.regions.map((r) => (
        <ScopeReading key={r.scope} s={r} bins={r.region_id ? m.regions[r.region_id]?.histogram : undefined} />
      ))}
      <div className="insight-overall">
        <Histogram
          bins={m.global.histogram}
          title="Whole-frame histogram"
          clipHigh={m.global.highlight_clip_fraction}
          clipLow={m.global.shadow_clip_fraction}
        />
        <ScopeReading s={insights.overall} />
      </div>
      <details className="how-to-read">
        <summary>How to read a histogram</summary>
        <ul className="small">
          {insights.how_to_read.map((t, i) => (
            <li key={i}>{t}</li>
          ))}
        </ul>
      </details>
      <p className="small muted">{insights.caveat}</p>
    </section>
  );
}

export function MeasurementsView({ m, regionLabels }: { m: M; regionLabels: Record<string, string> }) {
  const g = m.global;
  const regions = Object.entries(m.regions ?? {});
  return (
    <div className="measurements">
      <div className="table-wrap">
        <table className="compact-table">
          <caption className="sr-only">Measurements</caption>
          <thead>
            <tr>
              <th scope="col">Area</th>
              <th scope="col">Mean brightness (0–255)</th>
              <th scope="col">Pure white</th>
              <th scope="col">Pure black</th>
              <th scope="col">Sharpness (relative)</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Whole image</th>
              <td>{num(g.mean_luminance)}</td>
              <td>{pct(g.highlight_clip_fraction)}</td>
              <td>{pct(g.shadow_clip_fraction)}</td>
              <td>{num(g.laplacian_var, 0)}</td>
            </tr>
            {regions.map(([id, r]) => (
              <tr key={id}>
                <th scope="row">
                  {id}
                  {regionLabels[id] ? ` — ${regionLabels[id]}` : ""}
                </th>
                <td>{num(r.mean_luminance)}</td>
                <td>{pct(r.highlight_clip_fraction)}</td>
                <td>{pct(r.shadow_clip_fraction)}</td>
                <td>{num(r.laplacian_var, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {m.caveats?.length > 0 && (
        <ul className="caveats small">
          {m.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
