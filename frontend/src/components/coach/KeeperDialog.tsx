import { useEffect, useRef, useState } from "react";
import { imageUrl } from "../../api/client";
import type { Capture, Shot } from "../../api/types";
import { criterionMeta } from "../../ui/status";
import { exifLine } from "./model";
import { Kbd } from "./parts";

export interface KeeperDialogProps {
  capture: Capture;
  shot: Shot;
  /** Seq of the keeper this would replace, if any. */
  replacesSeq: number | null;
  onAccept: (notes: string) => void;
  onClose: () => void;
}

/** "Accept #13 as the keeper for …?" — keepers are only ever accepted by the photographer. */
export function KeeperDialog({ capture, shot, replacesSeq, onAccept, onClose }: KeeperDialogProps) {
  const [notes, setNotes] = useState("");
  const acceptRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const results = capture.latest_assessment?.result?.criterion_results ?? [];
  const text = (id: string) => shot.criteria.find((c) => c.id === id)?.text ?? id;
  const titleId = `keeper-title-${capture.id}`;
  const exif = exifLine(capture.exif);

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    acceptRef.current?.focus();
    return () => prev?.focus?.();
  }, []);

  return (
    <div className="cp-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={dialogRef}
        className="cp-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={(e) => {
          // Keep panel/voice shortcuts from firing underneath the dialog.
          e.stopPropagation();
          if (e.key === "Escape") {
            e.preventDefault();
            onClose();
          } else if (e.key === "Enter" && (e.target as HTMLElement).tagName !== "BUTTON") {
            e.preventDefault();
            onAccept(notes);
          } else if (e.key === "Tab") {
            const f = dialogRef.current?.querySelectorAll<HTMLElement>("button, input");
            if (!f?.length) return;
            const first = f[0];
            const last = f[f.length - 1];
            if (e.shiftKey && document.activeElement === first) {
              e.preventDefault();
              last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first.focus();
            }
          }
        }}
        onKeyUp={(e) => e.stopPropagation()}
      >
        <h2 id={titleId} className="cp-dialog-title">
          Accept #{capture.seq} as the keeper for {shot.title}?
        </h2>
        <div className="cp-dialog-body">
          <img className="cp-dialog-img" src={imageUrl(capture.id, "thumb")} alt={`Photo #${capture.seq}`} />
          <div className="cp-stack cp-gap-6">
            {results.map((cr) => {
              const m = criterionMeta(cr.result);
              return (
                <span key={cr.criterion_id}>
                  <span style={{ color: m.color }} className="cp-mono" aria-hidden="true">
                    {m.glyph}
                  </span>{" "}
                  <span className="cp-sr">{m.word}: </span>
                  {text(cr.criterion_id)}
                </span>
              );
            })}
            {exif && <span className="cp-mono cp-hint">{exif}</span>}
          </div>
        </div>
        <p className="cp-t2 cp-small">
          The coach can suggest a frame, but only you can accept it. You can revoke it later in Coverage.
          {replacesSeq != null && ` This replaces #${replacesSeq}.`}
        </p>
        <label className="cp-stack cp-gap-4">
          <span className="cp-label">Notes (optional)</span>
          <input className="cp-input" value={notes} maxLength={500} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <div className="cp-row cp-end">
          <button type="button" className="cp-btn cp-btn-l" onClick={onClose}>
            Not yet <Kbd>Esc</Kbd>
          </button>
          <button ref={acceptRef} type="button" className="cp-btn cp-btn-l cp-btn-pri" onClick={() => onAccept(notes)}>
            ★ Accept keeper <Kbd>↵</Kbd>
          </button>
        </div>
      </div>
    </div>
  );
}
