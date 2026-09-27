import { useEffect, useMemo, useState } from "react";
import { api, imageUrl } from "../api/client";
import type { Capture, Shot, ZoneName } from "../api/types";
import { useApp } from "../AppContext";
import { isRawOnlyNoPreview } from "../lib/filmstrip";
import { shotTitle } from "../lib/format";
import { defaultScope, scopeRows, WHOLE } from "../lib/inspector";
import { verdictMeta } from "../ui/status";
import { BrightnessInspector, ZONE_CAPTION } from "./Measurements";
import { RegionEditor } from "./RegionEditor";
import { ReceivedOverlay } from "./ShootStatus";

function ver(c: Capture): string {
  // Bust the (1 h) image cache when evidence appears or changes.
  return `?v=${c.evidence.available ? c.evidence.crops.map((x) => x.id).join("-") || "1" : "0"}`;
}

/** Whether an image URL loads, checked once per URL (zone masks may not exist on older captures). */
const imageOk = new Map<string, boolean>();
function useImageAvailable(url: string | null): boolean | null {
  const [ok, setOk] = useState<boolean | null>(url ? imageOk.get(url) ?? null : null);
  useEffect(() => {
    if (!url) return setOk(null);
    const known = imageOk.get(url);
    if (known !== undefined) return setOk(known);
    setOk(null);
    let alive = true;
    const img = new Image();
    img.onload = () => {
      imageOk.set(url, true);
      if (alive) setOk(true);
    };
    img.onerror = () => {
      imageOk.set(url, false);
      if (alive) setOk(false);
    };
    img.src = url;
    return () => {
      alive = false;
    };
  }, [url]);
  return ok;
}

/** Colour for a zone patch on the photo: lost detail is solid red/blue; ordinary zones get an accent tint. */
function zoneColor(z: ZoneName): string {
  return z === "clip_high" ? "var(--lost-hi)" : z === "clip_low" ? "var(--lost-lo)" : "color-mix(in oklch, var(--acc) 45%, transparent)";
}

function ZonePatch({ capture, zone }: { capture: Capture; zone: ZoneName }) {
  const url = imageUrl(capture.id, `zone_${zone}`) + ver(capture);
  const ok = useImageAvailable(url);
  const clip = zone === "clip_high" || zone === "clip_low";
  if (ok === false) {
    // No zone mask for this capture: lost-detail zones fall back to the combined clip overlay.
    return clip && capture.evidence.has_clip_overlay ? (
      <img className="zone-overlay" src={imageUrl(capture.id, "clip_overlay") + ver(capture)} alt="" aria-hidden="true" draggable={false} />
    ) : null;
  }
  if (!ok) return null;
  const mask = `url("${url}")`;
  return (
    <div
      className="zone-mask"
      aria-hidden="true"
      style={{ background: zoneColor(zone), maskImage: mask, WebkitMaskImage: mask }}
      data-testid={`zone-${zone}`}
    />
  );
}

function timeOf(c: Capture): string {
  const iso = c.capture_time ?? c.exif?.datetime_original ?? c.ready_at ?? c.detected_at;
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function CaptureViewer({
  capture,
  following,
  onFollow,
  showLost = false,
  onToggleLost,
}: {
  capture: Capture | null;
  following: boolean;
  onFollow: () => void;
  showLost?: boolean;
  onToggleLost?: () => void;
}) {
  const { state } = useApp();
  const [view, setView] = useState<"auto" | "photo" | "compare">("auto");
  const [pinScope, setPinScope] = useState<string | null>(null);
  const [hoverScope, setHoverScope] = useState<string | null>(null);
  const [pinZone, setPinZone] = useState<ZoneName | null>(null);
  const [hoverZone, setHoverZone] = useState<ZoneName | null>(null);
  const [natural, setNatural] = useState<{ id: string; w: number; h: number } | null>(null);
  const cid = capture?.id ?? null;
  useEffect(() => {
    setView("auto");
    setPinScope(null);
    setHoverScope(null);
  }, [cid]);

  // The coach can point at the photo ("Show me on the photo"): a window event picks the zone and region.
  useEffect(() => {
    const onShow = (e: Event) => {
      const d = (e as CustomEvent<{ zone?: ZoneName | null; regionId?: string | null }>).detail ?? {};
      setView("photo");
      if (d.zone !== undefined) setPinZone(d.zone);
      if (d.regionId !== undefined) setPinScope(d.regionId ?? WHOLE);
    };
    window.addEventListener("aa:show-zone", onShow);
    return () => window.removeEventListener("aa:show-zone", onShow);
  }, []);

  const shot: Shot | null = useMemo(() => {
    if (!state || !capture) return null;
    return state.shots.find((s) => s.id === capture.shot_id) ?? state.shots.find((s) => s.id === state.session.active_shot_id) ?? null;
  }, [state, capture]);
  const rows = useMemo(() => (capture ? scopeRows(capture, shot) : []), [capture, shot]);

  if (!state) return null;

  if (!capture) {
    const any = state.captures.length > 0;
    const active = state.shots.find((s) => s.id === state.session.active_shot_id);
    const lastFile = state.last_file_at ? Math.max(0, Math.round((Date.now() - Date.parse(state.last_file_at)) / 1000)) : null;
    return (
      <div className="stage-col">
        <div className="stage stage-mat">
          <div className="stage-top">
            <ReceivedOverlay />
          </div>
          <div className="stage-waiting" data-testid="stage-waiting">
            <span className="waiting-dot" aria-hidden="true" />
            <h2>{any ? "Ready for the first frame" : "Waiting for the first photo…"}</h2>
            <p className="waiting-sub">
              {any
                ? `${active?.title ?? "This shot"} · take the shot when you’re set`
                : "Photos are read from the watch folder. The app can’t see the camera itself."}
            </p>
            <p className="waiting-folder mono">
              {state.session.watch_folder
                ? `${state.watching ? "Watching" : "Not watching"} ${state.session.watch_folder}${lastFile != null ? ` · last file ${lastFile} s ago` : ""}`
                : "No watch folder set. Add one in Sessions, or import photos."}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const baseline = capture.baseline_capture_id ? state.captures.find((c) => c.id === capture.baseline_capture_id) ?? null : null;
  const mode = view === "auto" ? (baseline ? "compare" : "photo") : view === "compare" && !baseline ? "photo" : view;
  const scope = hoverScope ?? pinScope ?? defaultScope(rows);
  const zone = hoverZone ?? pinZone;
  const activeRegion = scope === WHOLE ? null : scope;
  const nat = natural?.id === capture.id ? natural : null;
  const aspect = nat ? nat.w / nat.h : capture.evidence.width && capture.evidence.height ? capture.evidence.width / capture.evidence.height : 4 / 3;
  const unreadable = !capture.evidence.available && (capture.processing_state === "failed" || isRawOnlyNoPreview(capture));
  const name = capture.jpeg_name ?? capture.source_names[0] ?? "";

  return (
    <div className="stage-col">
      <div className="stage stage-mat">
        <div className="stage-top">
          <ReceivedOverlay />
          {capture.attribution_ambiguous && <AttributionBanner capture={capture} />}
        </div>
        <div className="stage-controls stage-control">
          {!following && (
            <button type="button" className="stage-btn" onClick={onFollow} title="Go back to showing each new photo as it arrives">
              Pinned #{capture.seq} · <span className="stage-btn-act">Follow newest</span>
            </button>
          )}
          {baseline && (
            <div className="seg stage-seg" role="group" aria-label="Stage view">
              <button type="button" aria-pressed={mode === "photo"} onClick={() => setView("photo")}>
                Photo
              </button>
              <button type="button" aria-pressed={mode === "compare"} onClick={() => setView("compare")}>
                Before / after
              </button>
            </div>
          )}
          {mode === "photo" && capture.evidence.has_clip_overlay && (
            <button type="button" className="stage-btn" aria-pressed={showLost} aria-keyshortcuts="H" onClick={onToggleLost} title="Show lost detail (H)">
              <span className="swatch" style={{ background: "var(--lost-hi)" }} />
              <span className="swatch" style={{ background: "var(--lost-lo)" }} />
              Lost detail <span className="kbd">H</span>
            </button>
          )}
        </div>

        {unreadable ? (
          <UnreadableCapture capture={capture} />
        ) : mode === "compare" && baseline ? (
          <CompareView before={baseline} after={capture} />
        ) : (
          <div className="stage-fit">
            <RegionEditor
              key={capture.id}
              src={imageUrl(capture.id, "overview") + ver(capture)}
              alt={`Photo #${capture.seq}, ${shotTitle(state.shots, capture.shot_id)}`}
              shot={shot}
              aspect={aspect}
              onNaturalSize={(w, h) => setNatural({ id: capture.id, w, h })}
              activeRegionId={activeRegion}
              onHoverRegion={setHoverScope}
              onPickRegion={(id) => setPinScope(id)}
            >
              {showLost && capture.evidence.has_clip_overlay && (
                <img className="zone-overlay" src={imageUrl(capture.id, "clip_overlay") + ver(capture)} alt="" aria-hidden="true" draggable={false} />
              )}
              {zone && <ZonePatch capture={capture} zone={zone} />}
              <div className="stage-tag photo-info mono">
                #{capture.seq} · {name}
                {timeOf(capture) && ` · ${timeOf(capture)}`}
              </div>
              {(zone || showLost) && (
                <div className="stage-tag zone-caption">
                  <span className="swatch swatch-l" style={{ background: zone ? ZONE_CAPTION[zone].swatch : "var(--lost-hi)" }} />
                  {zone ? ZONE_CAPTION[zone].caption : "Solid red = pure white · solid blue = pure black"}
                </div>
              )}
            </RegionEditor>
          </div>
        )}
      </div>
      {mode === "photo" && !unreadable && (
        <BrightnessInspector
          capture={capture}
          rows={rows}
          scope={scope}
          pinnedScope={pinScope ?? defaultScope(rows)}
          onHoverScope={setHoverScope}
          onPinScope={(k) => setPinScope(k)}
          zone={zone}
          pinnedZone={pinZone}
          onHoverZone={setHoverZone}
          onPinZone={(z) => setPinZone((p) => (p === z ? null : z))}
        />
      )}
    </div>
  );
}

function UnreadableCapture({ capture }: { capture: Capture }) {
  const { run, refresh } = useApp();
  const rawOnly = isRawOnlyNoPreview(capture);
  const name = capture.raw_name ?? capture.source_names[0] ?? "";
  return (
    <div className="stage-waiting stage-problem" role="status">
      <span className="glyph tone-ret problem-glyph" aria-hidden="true">⚠</span>
      <h2>{rawOnly ? `#${capture.seq} is RAW-only${name ? ` (${name.split(".").pop()?.toUpperCase()})` : ""}` : `#${capture.seq} couldn’t be read`}</h2>
      <p className="waiting-sub">
        {rawOnly
          ? "There’s no preview to analyse. Set the camera to RAW+JPEG, or skip this file."
          : capture.error ?? "The file could not be decoded. The camera may still have been writing it."}
      </p>
      {!rawOnly && (
        <button
          type="button"
          className="btn-l stage-control"
          onClick={() =>
            run("Read again", async () => {
              await api.rereadCapture(capture.id);
              await refresh();
            })
          }
        >
          Read again
        </button>
      )}
    </div>
  );
}

/** "#16 might belong to Hero": move it or keep it where it is. */
function AttributionBanner({ capture }: { capture: Capture }) {
  const { state, run, refresh } = useApp();
  const [pick, setPick] = useState("");
  if (!state) return null;
  const hint = capture.attribution_hint ?? null;
  const assign = (shotId: string | null, label: string) =>
    run(label, async () => {
      await api.patchCapture(capture.id, { shot_id: shotId });
      await refresh();
    });
  const others = state.shots.filter((s) => s.id !== capture.shot_id);
  return (
    <div className="attr-banner stage-control" role="group" aria-label="Shot attribution">
      <span className="glyph tone-unc" aria-hidden="true">?</span>
      <span className="attr-text">
        #{capture.seq} might belong to {hint ? <b>{hint.shot_title}</b> : "another shot"}
        {hint?.seconds_after_switch != null && (
          <span className="attr-why"> · taken {Math.round(hint.seconds_after_switch)} s after you switched shots</span>
        )}
      </span>
      {hint ? (
        <button type="button" className="primary" onClick={() => void assign(hint.shot_id, "Move photo")}>
          Move to {hint.shot_title.split(/\s[—(-]/)[0]}
        </button>
      ) : (
        <>
          <label className="sr-only" htmlFor={`attr-${capture.id}`}>
            Move to shot
          </label>
          <select id={`attr-${capture.id}`} value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">Move to…</option>
            {others.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
          <button type="button" className="primary" disabled={!pick} onClick={() => void assign(pick, "Move photo")}>
            Move
          </button>
        </>
      )}
      <button type="button" onClick={() => void assign(capture.shot_id, "Keep photo here")}>
        Keep here
      </button>
    </div>
  );
}

/**
 * Before / after on the stage. Newest is always on the right, with the accent ring. The coach panel
 * holds the verdict, the measured changes, the per-region pairs and the "Compare with…" picker.
 */
function CompareView({ before, after }: { before: Capture; after: Capture }) {
  const cm = after.comparison_metrics?.baseline_capture_id === before.id ? after.comparison_metrics : null;
  const framing = cm?.framing ?? null;
  const bv = verdictMeta(before.latest_assessment?.result?.verdict);
  const av = verdictMeta(after.latest_assessment?.result?.verdict);
  return (
    <div className="compare" data-testid="before-after">
      <div className="compare-head">
        <span className="muted">
          Comparing #{after.seq} with <b className="compare-base">#{before.seq}</b>
          {after.baseline_overridden ? " · chosen by you" : ""}
        </span>
        {framing && (
          <span className={`compare-match mono${framing.comparable ? "" : " tone-unc"}`}>
            Framing match {Math.round(framing.score * 100)}%{framing.comparable ? "" : " · too low"}
          </span>
        )}
      </div>
      <div className="compare-photos">
        {[
          { c: before, tag: "BEFORE", v: bv },
          { c: after, tag: "AFTER", v: av },
        ].map(({ c, tag, v }) => (
          <figure key={tag} className="compare-fig">
            <figcaption>
              <span className="label-caps">{tag}</span> <b>#{c.seq}</b>{" "}
              <span style={{ color: v.color }}>
                <span className="glyph" aria-hidden="true">{v.glyph}</span> {v.word}
              </span>
            </figcaption>
            <div className={tag === "AFTER" ? "compare-img is-after" : "compare-img"}>
              <img src={imageUrl(c.id, "overview") + ver(c)} alt={`${tag === "AFTER" ? "After" : "Before"}: photo #${c.seq}`} />
            </div>
          </figure>
        ))}
      </div>
      <p className="compare-legend">
        Newest on the right. Region by region changes are in the coach panel. From JPEG previews, not RAW.
      </p>
    </div>
  );
}

export function fmtShutter(s: number): string {
  if (s >= 1) return `${s.toFixed(s >= 10 ? 0 : 1)} s`;
  return `1/${Math.round(1 / s)} s`;
}
