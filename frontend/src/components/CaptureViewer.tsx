import { useState } from "react";
import { api, imageUrl } from "../api/client";
import type { Capture, Crop, Shot } from "../api/types";
import { useApp } from "../AppContext";
import { humanize, shotTitle } from "../lib/format";
import { HistogramReading, MeasurementsView } from "./Measurements";
import { RegionEditor } from "./RegionEditor";

function ver(c: Capture): string {
  // Bust the (1 h) image cache when evidence appears or changes.
  return `?v=${c.evidence.available ? c.evidence.crops.map((x) => x.id).join("-") || "1" : "0"}`;
}

function CropFigure({ capture, crop, label }: { capture: Capture; crop: Crop; label?: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <figure className="crop">
      {failed ? (
        <div className="img-missing small">crop not available</div>
      ) : (
        <img
          src={imageUrl(capture.id, `crop_${crop.id}`) + ver(capture)}
          alt={`Crop ${crop.label} from photo #${capture.seq}`}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      )}
      <figcaption>
        {label ?? `#${capture.seq}`} · {crop.id}: {crop.label}
        {crop.source === "auto" && <strong className="badge badge-auto"> auto (not user-selected)</strong>}
        {!crop.native_resolution && <span className="small muted"> · scaled {crop.scale.toFixed(2)}×</span>}
      </figcaption>
    </figure>
  );
}

export function CaptureViewer({
  capture,
  following,
  onFollow,
}: {
  capture: Capture | null;
  following: boolean;
  onFollow: () => void;
}) {
  const { state, run, refresh } = useApp();
  const [showBA, setShowBA] = useState(true);
  const [showClip, setShowClip] = useState(false);
  const [compareWith, setCompareWith] = useState("");
  if (!state) return null;
  if (!capture) {
    return (
      <section className="panel viewer" aria-labelledby="viewer-h">
        <h2 id="viewer-h">Photo</h2>
        <p>No photos yet for this shot. Take a photo with the tethered camera, or import one on the Sessions tab.</p>
      </section>
    );
  }
  const shot: Shot | null =
    state.shots.find((s) => s.id === capture.shot_id) ??
    state.shots.find((s) => s.id === state.session.active_shot_id) ??
    null;
  const baseline = capture.baseline_capture_id
    ? state.captures.find((c) => c.id === capture.baseline_capture_id) ?? null
    : null;
  const sameShot = state.captures.filter((c) => c.shot_id === capture.shot_id && c.id !== capture.id);
  const la = capture.latest_assessment;
  const measurements = (la?.status === "completed" && la.measurements) || capture.evidence.measurements;
  const regionLabels: Record<string, string> = {};
  for (const c of capture.evidence.crops) regionLabels[c.id] = c.label;
  for (const r of shot?.sharp_regions ?? []) regionLabels[r.id] ??= r.label;

  return (
    <section className="panel viewer" aria-labelledby="viewer-h">
      <div className="viewer-head">
        <h2 id="viewer-h">
          Photo #{capture.seq} <span className="muted">· {shotTitle(state.shots, capture.shot_id)}</span>
        </h2>
        <span className="small">
          {following ? (
            "Following newest photo"
          ) : (
            <>
              Pinned to #{capture.seq}{" "}
              <button type="button" onClick={onFollow}>
                Follow newest
              </button>
            </>
          )}
        </span>
      </div>
      <p className="small muted">
        {capture.jpeg_name ?? capture.source_names.join(", ")}
        {capture.raw_name ? ` + RAW ${capture.raw_name}` : ""} · {humanize(capture.processing_state)}
        {capture.exif?.exposure_known &&
          ` · ${capture.exif.exposure_time_s ? fmtShutter(capture.exif.exposure_time_s) : "?"} f/${capture.exif.f_number ?? "?"} ISO ${capture.exif.iso ?? "?"}`}
        {capture.user_reported_change && ` · changed: “${capture.user_reported_change}”`}
      </p>

      {baseline && (
        <label className="check">
          <input type="checkbox" checked={showBA} onChange={(e) => setShowBA(e.target.checked)} />
          Show before/after (baseline #{baseline.seq}
          {capture.baseline_overridden ? ", chosen by you" : ""})
        </label>
      )}

      {baseline && showBA ? (
        <BeforeAfter before={baseline} after={capture} />
      ) : (
        <>
          {capture.evidence.has_clip_overlay && (
            <label className="check">
              <input type="checkbox" checked={showClip} onChange={(e) => setShowClip(e.target.checked)} />
              Show lost detail on the photo (<span className="swatch swatch-red">red</span> = pure white,{" "}
              <span className="swatch swatch-blue">blue</span> = pure black)
            </label>
          )}
          <RegionEditor
            key={capture.id}
            src={imageUrl(capture.id, "overview") + ver(capture)}
            alt={`Overview of photo #${capture.seq}`}
            shot={shot}
            overlaySrc={showClip && capture.evidence.has_clip_overlay ? imageUrl(capture.id, "clip_overlay") + ver(capture) : null}
          />
          {capture.evidence.crops.length > 0 && (
            <div className="crops">
              {capture.evidence.crops.map((c) => (
                <CropFigure key={c.id} capture={capture} crop={c} />
              ))}
            </div>
          )}
        </>
      )}

      {capture.shot_id && sameShot.length > 0 && (
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!compareWith) return;
            void run("Compare", async () => {
              await api.patchCapture(capture.id, { baseline_capture_id: compareWith });
              await api.compare(capture.id, compareWith);
              await refresh();
            });
          }}
        >
          <label>
            Compare with…
            <select value={compareWith} onChange={(e) => setCompareWith(e.target.value)}>
              <option value="">choose a photo of this shot</option>
              {sameShot.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.seq}
                  {c.id === capture.baseline_capture_id ? " (current baseline)" : ""}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={!compareWith}>
            Compare
          </button>
        </form>
      )}

      {measurements && capture.histogram_insights && (
        <HistogramReading insights={capture.histogram_insights} m={measurements} changes={capture.histogram_changes} />
      )}
      {measurements ? (
        <details className="measure-details">
          <summary>Measurements (numbers)</summary>
          <MeasurementsView m={measurements} regionLabels={regionLabels} />
        </details>
      ) : (
        <p className="small muted">Measurements appear once evidence is ready.</p>
      )}
    </section>
  );
}

function BeforeAfter({ before, after }: { before: Capture; after: Capture }) {
  const afterCrops = after.evidence.crops;
  return (
    <div className="before-after" data-testid="before-after">
      <div className="ba-row">
        <figure>
          <img src={imageUrl(before.id, "overview") + ver(before)} alt={`Before: overview of photo #${before.seq}`} />
          <figcaption>Before · #{before.seq}</figcaption>
        </figure>
        <figure>
          <img src={imageUrl(after.id, "overview") + ver(after)} alt={`After: overview of photo #${after.seq}`} />
          <figcaption>After · #{after.seq}</figcaption>
        </figure>
      </div>
      {afterCrops.map((ac) => {
        const bc = before.evidence.crops.find((x) => x.id === ac.id);
        return (
          <div className="ba-row" key={ac.id}>
            {bc ? <CropFigure capture={before} crop={bc} label={`Before #${before.seq}`} /> : <div className="img-missing small">no matching crop in #{before.seq}</div>}
            <CropFigure capture={after} crop={ac} label={`After #${after.seq}`} />
          </div>
        );
      })}
    </div>
  );
}

export function fmtShutter(s: number): string {
  if (s >= 1) return `${s.toFixed(s >= 10 ? 0 : 1)} s`;
  return `1/${Math.round(1 / s)} s`;
}
