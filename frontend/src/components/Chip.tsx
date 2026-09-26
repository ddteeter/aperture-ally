import { humanize } from "../lib/format";

/** A status chip: the state is always written out in text; colour is only a secondary cue. */
export function Chip({ value, kind, label }: { value: string | null | undefined; kind?: string; label?: string }) {
  const v = value ?? "none";
  return (
    <span className={`chip chip-${kind ?? v}`}>
      {label ? <span className="chip-label">{label}: </span> : null}
      {humanize(v)}
    </span>
  );
}
