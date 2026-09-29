import { useEffect, useRef, useState } from "react";
import { api, imageUrl } from "../../api/client";
import type { ModelCallView } from "../../api/types";

/** "What the coach saw": the exact request and raw response behind one assessment (desk use). */
export function CoachSaw({ assessmentId, captureId, onClose }: { assessmentId: string; captureId: string; onClose: () => void }) {
  const [calls, setCalls] = useState<ModelCallView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    api.assessmentCalls(assessmentId).then(setCalls).catch((e) => setError(String(e)));
    box.current?.focus();
  }, [assessmentId]);

  return (
    <div
      ref={box}
      tabIndex={-1}
      className="cp-dialog cp-saw"
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
      <div className="cp-row">
        <h3 id="saw-h" className="cp-h">What the coach saw</h3>
        <button type="button" className="cp-btn" onClick={onClose}>
          Close
        </button>
      </div>
      {error && <p className="cp-note">Couldn't load: {error}</p>}
      {!calls && !error && <p className="cp-note">Loading…</p>}
      {calls?.length === 0 && <p className="cp-note">No stored request for this result (model I/O storage may be off).</p>}
      {calls?.map((c) => {
        const ctx = (c.request.context ?? {}) as Record<string, unknown>;
        const prefs = (ctx.preferences ?? {}) as Record<string, string | null>;
        const meta = (ctx.metadata ?? {}) as Record<string, unknown>;
        const capture = (ctx.capture ?? {}) as Record<string, unknown>;
        return (
          <section key={c.id} className="cp-stack cp-gap-6" data-testid="saw-call">
            <p className="cp-model">
              {c.attempt ? "Repair · " : ""}
              {c.provider} · {c.model_resolved ?? c.model_requested} · prompt {c.prompt_version} ·{" "}
              {c.latency_ms != null ? `${(c.latency_ms / 1000).toFixed(1)} s` : "—"} · in/out{" "}
              {c.usage.input_tokens ?? "?"}/{c.usage.output_tokens ?? "?"} tokens · {c.status}
            </p>
            <div>
              <span className="cp-label">Preferences applied</span>
              <ul className="cp-causes">
                {(["yours", "project", "template", "shoot"] as const).map((k) => (
                  <li key={k}>
                    <strong>{k}:</strong> {prefs[k] || <span className="cp-note">none</span>}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <span className="cp-label">Camera metadata sent</span>
              <p className="cp-body-text">
                {Object.keys(meta).length
                  ? Object.entries(meta)
                      .map(([k, v]) => `${k}: ${String(v)}`)
                      .join(" · ")
                  : "none (no EXIF)"}
                {capture.raw_kept != null && ` · RAW kept: ${capture.raw_kept ? "yes" : "no"} (${String(capture.basis ?? "")})`}
              </p>
            </div>
            <div>
              <span className="cp-label">Images sent ({c.request.images?.length ?? 0})</span>
              <div className="cp-saw-images">
                {c.request.images?.map((im, i) => {
                  const kind = im.kind === "overview" ? "overview" : `crop_${im.region_id}`;
                  return (
                    <figure key={i}>
                      {im.role === "current" ? <img src={imageUrl(captureId, kind as never)} alt="" /> : <span className="cp-note">baseline</span>}
                      <figcaption className="cp-note">{im.label}</figcaption>
                    </figure>
                  );
                })}
              </div>
            </div>
            <details>
              <summary>Instructions</summary>
              <pre className="cp-saw-pre">{c.request.instructions}</pre>
            </details>
            <details>
              <summary>Full context (JSON)</summary>
              <pre className="cp-saw-pre">{JSON.stringify(ctx, null, 2)}</pre>
            </details>
            <details>
              <summary>Raw response</summary>
              <pre className="cp-saw-pre">{c.response_text}</pre>
            </details>
            {c.validation_errors.length > 0 && <p className="cp-note">Validation: {c.validation_errors.join("; ")}</p>}
          </section>
        );
      })}
    </div>
  );
}
