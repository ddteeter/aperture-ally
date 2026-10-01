import { useEffect, useRef, useState } from "react";
import { api, imageUrl } from "../../api/client";
import type { Assessment, Capture, ModelCallView, Shot } from "../../api/types";
import { useApp } from "../../AppContext";
import { verdictMeta } from "../../ui/status";
import { providerLabel, verdictKind } from "./model";
import "./coachsaw.css";

/** "What the coach saw" (desk only, read-only): what went in on the left — images, camera metadata, RAW
 *  status — and on the right the preference levels, what came back, the instructions and raw response. */

const META_LABEL: Record<string, string> = {
  camera: "Camera",
  lens: "Lens",
  focal_length_mm: "Focal length",
  exposure_program: "Mode",
  f_number: "Aperture",
  exposure_time: "Shutter",
  exposure_time_s: "Shutter",
  iso: "ISO",
  exposure_compensation: "Exposure comp.",
  exposure_compensation_ev: "Exposure comp.",
  focus_mode: "Focus",
  white_balance: "White balance",
  stabilization: "Stabilisation",
  flash_fired: "Flash",
};

function metaValue(k: string, v: unknown): string {
  if (v == null) return "—";
  if (k === "f_number" && typeof v === "number") return `f/${v}`;
  if ((k === "exposure_time" || k === "exposure_time_s") && typeof v === "number") return v >= 1 ? `${v} s` : `1/${Math.round(1 / v)} s`;
  if (k === "focal_length_mm" && typeof v === "number") return `${v} mm`;
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

const LEVELS: { key: "shoot" | "template" | "project" | "yours"; label: string }[] = [
  { key: "shoot", label: "Today" },
  { key: "template", label: "Template" },
  { key: "project", label: "Project" },
  { key: "yours", label: "Your defaults" },
];

function words(s: string | undefined): number {
  return s ? s.trim().split(/\s+/).length : 0;
}

function clock(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function sawAsText(a: Assessment, call: ModelCallView | undefined): string {
  const r = a.result;
  const prefs = ((call?.request.context ?? {}) as Record<string, unknown>).preferences as Record<string, string | null> | undefined;
  return [
    `Verdict: ${r ? verdictMeta(r.verdict).word : a.status}`,
    r ? `Spoken: ${r.spoken_text}` : `Error: ${a.error ?? "none"}`,
    ...(r?.fixable_in_post?.length ? [`Fixable in post: ${r.fixable_in_post.join("; ")}`] : []),
    ...LEVELS.map((l) => `${l.label}: ${prefs?.[l.key] ?? "not set"}`),
    `Model: ${a.model_resolved ?? a.model_requested ?? "?"} · prompt ${a.prompt_version}`,
  ].join("\n");
}

export function CoachSaw({ a, capture, shot, onClose }: { a: Assessment; capture: Capture; shot: Shot | null; onClose: () => void }) {
  const { state, toast } = useApp();
  const [calls, setCalls] = useState<ModelCallView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [instr, setInstr] = useState(false);
  const [raw, setRaw] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    api.assessmentCalls(a.id).then(setCalls).catch((e) => setError(String(e)));
    const prev = document.activeElement as HTMLElement | null;
    box.current?.focus();
    return () => prev?.focus?.();
  }, [a.id]);

  const last = calls?.[calls.length - 1];
  const earlier = calls && calls.length > 1 ? calls.slice(0, -1) : [];
  const ctx = (last?.request.context ?? {}) as Record<string, unknown>;
  const prefs = (ctx.preferences ?? {}) as Record<string, string | null>;
  const meta = (ctx.metadata ?? {}) as Record<string, unknown>;
  const cap = (ctx.capture ?? {}) as Record<string, unknown>;
  const images = last?.request.images ?? [];
  const crops = images.filter((im) => im.kind !== "overview");
  const overview = images.find((im) => im.kind === "overview" && im.role === "current");
  const r = a.result;
  const failed = a.status === "failed";
  const early = a.early_speech;
  const firstS = early?.ready_ms != null ? `${(early.ready_ms / 1000).toFixed(1)} s` : null;
  const allS = a.timings?.total_ms != null ? `${(a.timings.total_ms / 1000).toFixed(1)} s` : null;
  const inTok = calls?.reduce((n, c) => n + (c.usage.input_tokens ?? 0), 0) ?? 0;
  const outTok = calls?.reduce((n, c) => n + (c.usage.output_tokens ?? 0), 0) ?? 0;
  // Claude reports cache reads beside input_tokens; OpenAI/Gemini report cached tokens within it.
  const cacheRead = calls?.reduce((n, c) => n + (c.usage.cache_read_input_tokens ?? 0), 0) ?? 0;
  const cachedWithin = calls?.reduce((n, c) => n + (c.usage.cached_input_tokens ?? 0), 0) ?? 0;
  const inAll = inTok + cacheRead + (calls?.reduce((n, c) => n + (c.usage.cache_creation_input_tokens ?? 0), 0) ?? 0);
  const cached = cacheRead + cachedWithin;
  const k = r ? verdictKind(r) : null;
  const vm = r ? verdictMeta(r.verdict) : null;
  const word = k === "usable" ? "Usable" : k === "usable_but" ? "Usable, but…" : vm?.word;
  const rawKept = cap.raw_kept as boolean | undefined;
  const subject = ((ctx.measurements ?? {}) as Record<string, unknown>).subject as
    | { fraction: number; touches_edge: string[]; background_to_subject_sharpness?: number | null; background_busyness?: number;
        subject_mean_luminance?: number; background_mean_luminance?: number }
    | undefined;
  const check = ctx.subject_check as { labels?: [string, number][]; distance_to_baseline?: number | null } | null | undefined;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sawAsText(a, last));
      toast({ glyph: "✓", text: "Copied", tone: "neutral" });
    } catch {
      toast({ glyph: "!", text: "Couldn't copy to the clipboard", tone: "unc" });
    }
  };
  const exportJson = () => {
    const blob = new Blob([JSON.stringify({ assessment: a, calls }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = Object.assign(document.createElement("a"), { href: url, download: `coach-saw-${capture.seq}.json` });
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div
      ref={box}
      tabIndex={-1}
      className="saw"
      role="dialog"
      aria-modal="true"
      aria-labelledby="saw-h"
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
      }}
    >
      <div className="saw-bar">
        <button type="button" className="saw-btn" onClick={onClose}>
          ← Back to shoot <span className="saw-t3 saw-mono">Esc</span>
        </button>
        <div className="saw-stack-0">
          <h2 id="saw-h" className="saw-title">
            What the coach saw · #{capture.seq}
          </h2>
          <span className="saw-xs saw-t3">
            {[state?.session.name, shot?.title, clock(capture.capture_time ?? capture.detected_at), "read-only"].filter(Boolean).join(" · ")}
          </span>
        </div>
        <div className="saw-bar-right">
          <button type="button" className="saw-btn" onClick={() => void copy()}>
            Copy as text
          </button>
          <button type="button" className="saw-btn" disabled={!calls} onClick={exportJson}>
            Export .json
          </button>
        </div>
      </div>

      {!calls && !error ? (
        <div className="saw-body">
          <div className="saw-left">
            <div className="saw-skel saw-skel-43" />
            <div className="saw-crops">
              <div className="saw-skel saw-sq" />
              <div className="saw-skel saw-sq" />
              <div className="saw-skel saw-sq" />
            </div>
          </div>
          <div className="saw-right">
            <div className="saw-skel saw-skel-20 saw-w40" />
            <div className="saw-skel saw-skel-90" />
            <div className="saw-skel saw-skel-90 saw-o6" />
            <span className="saw-small saw-t3">Opening the record for #{capture.seq}…</span>
          </div>
        </div>
      ) : (
        <div className="saw-body">
          <div className="saw-left">
            {error && <p className="saw-note">Couldn't load the stored request: {error}</p>}
            {calls?.length === 0 && <p className="saw-note">No stored request for this result (model I/O storage may be off).</p>}
            {images.length > 0 && (
              <div className="saw-stack-8">
                <span className="saw-eyebrow">
                  IMAGES SENT · {overview ? "1 OVERVIEW" : "NO OVERVIEW"}
                  {crops.length ? ` + ${crops.length} ${crops.length === 1 ? "CROP" : "CROPS"}` : ""}
                </span>
                {overview && <img className="saw-overview" src={imageUrl(capture.id, "overview")} alt={`Overview sent for #${capture.seq}`} />}
                {crops.length > 0 && (
                  <div className="saw-crops">
                    {crops.map((im, i) => (
                      <figure key={i} className="saw-crop">
                        {im.role === "current" ? (
                          <img src={imageUrl(capture.id, `crop_${im.region_id}` as never)} alt="" />
                        ) : (
                          <div className="saw-crop-ph">baseline</div>
                        )}
                        <figcaption className="saw-stack-0">
                          <span className="saw-xs saw-strong">{im.label.replace(/^current crop '|'.*$/g, "")}</span>
                          <span className="saw-mono saw-xxs saw-t3">
                            {im.role}
                            {im.bytes ? ` · ${Math.round(im.bytes / 1024)} KB` : ""}
                          </span>
                        </figcaption>
                      </figure>
                    ))}
                  </div>
                )}
              </div>
            )}
            {Object.keys(meta).length > 0 && (
              <div className="saw-stack-6">
                <span className="saw-eyebrow">CAMERA METADATA SENT</span>
                <dl className="saw-meta">
                  {Object.entries(meta).map(([mk, mv]) => (
                    <div key={mk} className="saw-meta-row">
                      <dt>{META_LABEL[mk] ?? mk.replace(/_/g, " ")}</dt>
                      <dd>{metaValue(mk, mv)}</dd>
                    </div>
                  ))}
                  {shot && (
                    <div className="saw-meta-row">
                      <dt>Shot</dt>
                      <dd>
                        {shot.ordinal + 1} · {shot.title} ({shot.criteria.length} criteria)
                      </dd>
                    </div>
                  )}
                </dl>
              </div>
            )}
            {subject && (
              <div className="saw-stack-6" data-testid="saw-subject">
                <span className="saw-eyebrow">SUBJECT · ON-DEVICE (APPLE VISION)</span>
                <dl className="saw-meta">
                  <div className="saw-meta-row">
                    <dt>Fills</dt>
                    <dd>
                      {Math.round(subject.fraction * 100)}% of the frame
                      {subject.touches_edge.length ? ` · touches ${subject.touches_edge.join(", ")} edge` : " · not cut off"}
                    </dd>
                  </div>
                  {subject.background_to_subject_sharpness != null && (
                    <div className="saw-meta-row">
                      <dt>Background sharpness</dt>
                      <dd>
                        {subject.background_to_subject_sharpness}× the subject's
                        {subject.background_to_subject_sharpness > 1 ? " (subject softer: focus or motion?)" : subject.background_to_subject_sharpness < 0.5 ? " (clearly softer)" : ""}
                      </dd>
                    </div>
                  )}
                  {subject.background_busyness != null && (
                    <div className="saw-meta-row">
                      <dt>Background busyness</dt>
                      <dd>{subject.background_busyness}</dd>
                    </div>
                  )}
                  {subject.subject_mean_luminance != null && (
                    <div className="saw-meta-row">
                      <dt>Brightness</dt>
                      <dd>
                        subject {subject.subject_mean_luminance} · background {subject.background_mean_luminance}
                      </dd>
                    </div>
                  )}
                  {check?.labels && (
                    <div className="saw-meta-row">
                      <dt>Looks like</dt>
                      <dd>{check.labels.map(([n]) => n).join(", ") || "—"}</dd>
                    </div>
                  )}
                  {check?.distance_to_baseline != null && (
                    <div className="saw-meta-row">
                      <dt>vs baseline</dt>
                      <dd>
                        {check.distance_to_baseline} {check.distance_to_baseline < 0.5 ? "(same subject)" : check.distance_to_baseline > 0.8 ? "(different subject or scene)" : ""}
                      </dd>
                    </div>
                  )}
                </dl>
              </div>
            )}
            {rawKept != null && (
              <div className="saw-card">
                <span className={rawKept ? "saw-mono saw-ok saw-bold" : "saw-mono saw-t3 saw-bold"}>{rawKept ? "✓" : "–"}</span>
                <span>
                  <b className="saw-bold">{rawKept ? "RAW was being kept" : "No RAW for this photo"}</b>
                  {rawKept
                    ? `${capture.raw_name ? ` (${capture.raw_name})` : ""}. The coach was told, so it treated highlight and colour issues as recoverable. It only saw the JPEG.`
                    : ". The coach was told highlights and colour are baked in."}
                </span>
              </div>
            )}
          </div>

          <div className="saw-right">
            {failed && (
              <div role="alert" className="saw-alert">
                <span className="saw-mono saw-ret saw-bold">✕</span>
                <span className="saw-stack-4 saw-grow">
                  <span className="saw-body-l saw-bold">Nothing came back for #{capture.seq}</span>
                  <span className="saw-small saw-t2">
                    {a.error ?? "The call failed."} Everything that was sent is still shown here. No advice was given for this photo.
                  </span>
                </span>
              </div>
            )}
            <div className="saw-stack-6">
              <span className="saw-eyebrow">PREFERENCES AS APPLIED · MOST SPECIFIC FIRST</span>
              {LEVELS.map((l) => (
                <div key={l.key} className="saw-level">
                  <span className="saw-xs saw-bold">{l.label}</span>
                  <span className="saw-body-s">{prefs[l.key] || <span className="saw-t3">not set</span>}</span>
                  <span className="saw-xxs saw-t2">{prefs[l.key] ? "applied" : ""}</span>
                </div>
              ))}
            </div>
            {r && (
              <div className="saw-stack-8">
                <span className="saw-eyebrow">WHAT CAME BACK</span>
                <dl className="saw-back">
                  <dt>Verdict</dt>
                  <dd className="saw-bold" style={{ color: vm?.color }}>
                    <span className="saw-mono">{vm?.glyph}</span> {word}
                  </dd>
                  {early ? (
                    <>
                      <dt>Spoken first</dt>
                      <dd>
                        “{early.text}” {firstS && <span className="saw-mono saw-xxs saw-t3">at {firstS}</span>}
                      </dd>
                      <dt>Final advice</dt>
                      <dd>
                        {early.corrected ? `Corrected${allS ? ` at ${allS}` : ""}: “${r.spoken_text}”` : `Same as spoken${allS ? `, validated at ${allS}` : ""}. No correction.`}
                      </dd>
                    </>
                  ) : (
                    <>
                      <dt>Spoken</dt>
                      <dd>“{r.spoken_text}”</dd>
                    </>
                  )}
                  {(r.fixable_in_post?.length ?? 0) > 0 && (
                    <>
                      <dt>Fixable in post</dt>
                      <dd className="saw-t2">{r.fixable_in_post!.join(" · ")}</dd>
                    </>
                  )}
                </dl>
              </div>
            )}
            {last && (
              <div className="saw-fold">
                <button type="button" className="saw-fold-btn" aria-expanded={instr} onClick={() => setInstr((v) => !v)}>
                  <span className="saw-mono saw-xxs saw-t3">{instr ? "▾" : "▸"}</span>
                  <span className="saw-strong">Instructions sent</span>
                  <span className="saw-mono saw-xs saw-t3 saw-push">
                    {last.prompt_version} · {words(last.request.instructions).toLocaleString("en-GB")} words
                  </span>
                </button>
                {instr && <pre className="saw-pre">{last.request.instructions}</pre>}
              </div>
            )}
            {last && (
              <div className="saw-fold">
                <button type="button" className="saw-fold-btn" aria-expanded={raw} onClick={() => setRaw((v) => !v)}>
                  <span className="saw-mono saw-xxs saw-t3">{raw ? "▾" : "▸"}</span>
                  <span className="saw-strong">Raw response</span>
                  <span className="saw-mono saw-xs saw-t3 saw-push">
                    {last.response_text
                      ? `JSON · ${last.usage.output_tokens ?? "?"} tokens · ${last.validation_errors.length ? "validation failed" : "validated ✓"}`
                      : "empty"}
                  </span>
                </button>
                {raw && (
                  <div className="saw-stack-8">
                    <pre className="saw-pre">{last.response_text ?? "// no response body"}</pre>
                    {last.validation_errors.length > 0 && <p className="saw-note">Validation: {last.validation_errors.join("; ")}</p>}
                    {earlier.map((c) => (
                      <details key={c.id} className="saw-earlier">
                        <summary>
                          Earlier attempt {c.attempt + 1} · {c.status}
                          {c.validation_errors.length ? ` · ${c.validation_errors.length} validation errors` : ""}
                        </summary>
                        <pre className="saw-pre">{c.response_text}</pre>
                      </details>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div className="saw-stats">
              {[
                ["Model", `${providerLabel(a.provider)} · ${a.model_resolved ?? a.model_requested ?? "?"}`],
                ["Latency", failed ? `${allS ?? "?"} · failed` : [firstS && `${firstS} first`, allS && `${allS} all`].filter(Boolean).join(" · ") || "—"],
                [
                  "Tokens",
                  `${inAll.toLocaleString("en-GB")} in${cached ? ` (${cached.toLocaleString("en-GB")} cached)` : ""} · ${outTok.toLocaleString("en-GB")} out`,
                ],
                ["Cost", a.cost_estimate_usd != null ? `$${a.cost_estimate_usd.toFixed(3)}` : a.provider === "mock" ? "$0 (mock)" : "n/a"],
              ].map(([sk, sv]) => (
                <div key={sk} className="saw-stat">
                  <span className="saw-xxs saw-t3">{sk}</span>
                  <span className="saw-mono saw-small">{sv}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
