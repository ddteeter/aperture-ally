import type { ReactNode } from "react";
import type { StatusMeta } from "../../ui/status";

export function Label({ children, tone }: { children: ReactNode; tone?: string }) {
  return (
    <span className="cp-label" style={tone ? { color: tone } : undefined}>
      {children}
    </span>
  );
}

/** Big glyph tile + word + meta line (verdict, comparison, failure, paused headers). */
export function GlanceHead({
  meta,
  sub,
  size = "l",
  wordTone = true,
  outline = false,
  tag,
}: {
  meta: StatusMeta;
  sub: ReactNode;
  size?: "l" | "m";
  wordTone?: boolean;
  /** Outlined tile (analysing) instead of a tinted one. */
  outline?: boolean;
  tag?: string | null;
}) {
  return (
    <div className="cp-head">
      <div
        className={`cp-tile${outline ? " is-outline" : ""}`}
        style={outline ? { borderColor: meta.color, color: meta.color } : { background: meta.tint, color: meta.color }}
        aria-hidden="true"
      >
        {meta.glyph}
      </div>
      <div className="cp-head-text">
        <h3 className={`cp-word cp-word-${size}`} style={wordTone ? { color: meta.color } : undefined}>
          {meta.word}
        </h3>
        <span className="cp-sub">{sub}</span>
      </div>
      {tag && <span className="cp-tag">{tag}</span>}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="cp-kbd">{children}</kbd>;
}
