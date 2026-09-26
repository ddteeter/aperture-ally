import type { Measurements as M } from "../api/types";
import { num, pct } from "../lib/format";

export function Histogram({ bins, title = "Luminance histogram" }: { bins: number[]; title?: string }) {
  const w = 256;
  const h = 64;
  const max = Math.max(...bins, 1e-9);
  const bw = w / Math.max(bins.length, 1);
  return (
    <svg
      className="histogram"
      viewBox={`0 0 ${w} ${h}`}
      width={w}
      height={h}
      role="img"
      aria-label={`${title}: ${bins.length} bins from black (left) to white (right)`}
    >
      <title>{title}</title>
      <rect x={0} y={0} width={w} height={h} className="hist-bg" />
      {bins.map((b, i) => {
        const bh = (b / max) * (h - 2);
        return <rect key={i} x={i * bw} y={h - bh} width={Math.max(bw - 0.5, 0.5)} height={bh} className="hist-bar" />;
      })}
    </svg>
  );
}

export function MeasurementsView({ m, regionLabels }: { m: M; regionLabels: Record<string, string> }) {
  const g = m.global;
  const regions = Object.entries(m.regions ?? {});
  return (
    <div className="measurements">
      <Histogram bins={g.histogram} />
      <div className="table-wrap">
        <table className="compact-table">
          <caption className="sr-only">Measurements</caption>
          <thead>
            <tr>
              <th scope="col">Area</th>
              <th scope="col">Mean luminance</th>
              <th scope="col">Highlight clip</th>
              <th scope="col">Shadow clip</th>
              <th scope="col">Sharpness (laplacian var)</th>
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
