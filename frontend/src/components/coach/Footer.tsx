import { useState, type RefObject } from "react";
import { api } from "../../api/client";
import type { Capture } from "../../api/types";
import { useApp } from "../../AppContext";
import { exifCells } from "./model";
import { Kbd, Label } from "./parts";

export function CameraExif({ capture }: { capture: Capture }) {
  return (
    <div className="cp-stack cp-gap-8 cp-exif-wrap">
      <Label>Camera · from EXIF</Label>
      <dl className="cp-exif">
        {exifCells(capture.exif).map((c) => (
          <div key={c.k}>
            <dt>{c.k}</dt>
            <dd className={c.missing ? "is-missing" : undefined} title={c.v}>
              {c.v}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export type KeeperMode =
  | { kind: "none" }
  | { kind: "accepted"; seq: number }
  /** primary: the coach thinks this frame is usable (48px button); otherwise a quieter "anyway" link. */
  | { kind: "offer"; seq: number; primary: boolean };

export function KeeperActions({ mode, onOpen, onUndo, onTakeAnother }: { mode: KeeperMode; onOpen: () => void; onUndo: () => void; onTakeAnother: () => void }) {
  if (mode.kind === "none") return null;
  if (mode.kind === "accepted") {
    return (
      <div className="cp-accepted" data-testid="keeper">
        <span className="cp-star" aria-hidden="true">
          ★
        </span>
        Keeper accepted · #{mode.seq}
        <button type="button" className="cp-link cp-push" onClick={onUndo}>
          Undo
        </button>
      </div>
    );
  }
  if (!mode.primary) {
    return (
      <div className="cp-row" data-testid="keeper">
        <button type="button" className="cp-link" onClick={onOpen}>
          Accept #{mode.seq} as keeper anyway…
        </button>
      </div>
    );
  }
  return (
    <div className="cp-row" data-testid="keeper">
      <button type="button" className="cp-btn cp-btn-xl cp-btn-pri cp-grow" onClick={onOpen}>
        <span aria-hidden="true">★</span> Accept #{mode.seq} as keeper… <Kbd>⌘↵</Kbd>
      </button>
      <button type="button" className="cp-btn cp-btn-xl" onClick={onTakeAnother}>
        Take another
      </button>
    </div>
  );
}

/** "What I changed" — attached to the next photo of the active shot (server keeps it as pending_change). */
export function ChangeNoteInput({ inputRef }: { inputRef: RefObject<HTMLInputElement | null> }) {
  const { sid, state, run, pendingNote: localNote, setPendingNote, toast } = useApp();
  const [text, setText] = useState("");
  if (!sid || !state) return null;
  const pending = state.pending_change !== undefined ? state.pending_change : localNote;
  const save = async (value: string | null) => {
    const r = await run(value ? "Save change note" : "Clear change note", () => api.changeNote(sid, value));
    if (r) {
      setPendingNote(r.pending_change);
      if (value) {
        setText("");
        toast({ glyph: "✓", text: `Change noted: ${value}`, source: "KEYBOARD" });
      }
    }
  };
  return (
    <div className="cp-stack cp-gap-6">
      <label className="cp-label" htmlFor="cp-changed">
        What I changed
      </label>
      <input
        id="cp-changed"
        ref={inputRef}
        className="cp-input cp-input-l"
        value={text}
        maxLength={500}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && text.trim()) {
            e.preventDefault();
            void save(text.trim());
          }
        }}
        placeholder="Hold the remote and say it, or type and press ↵"
      />
      {pending && (
        <p className="cp-hint" role="status">
          For the next photo: “{pending}”{" "}
          <button type="button" className="cp-link" onClick={() => void save(null)}>
            Clear
          </button>
        </p>
      )}
    </div>
  );
}
