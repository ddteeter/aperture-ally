import { useId } from "react";

/** The Aperture Ally mark (mark 2a, "The blade that speaks": docs/design/icons). Six iris blades; only the
 *  lower-left one, with the speech tail, takes the accent. The gaps are real transparency (a mask), so it
 *  works on any background. Colours come from --mark-blade / --mark-speak, which follow the theme.
 *  Below 24 px the gaps widen, as the design's favicon does. Never rotate it: the tail points lower-left. */

const BLADE = "M7 12.12 L-8.56 39.07 A40 40 0 0 1 -38.12 12.12 Z";
const SPEAKING = "M7 12.12 L-8.56 39.07 A40 40 0 0 1 -18.78 35.32 L-45 46 L-33.16 22.37 A40 40 0 0 1 -38.12 12.12 Z";
const TURNS = [60, 120, 180, 240, 300];

export function Mark({ size = 18, title }: { size?: number; title?: string }) {
  const id = useId().replace(/:/g, "");
  const gap = size < 24 ? 4.5 : 3.5;
  return (
    <svg
      className="mark"
      viewBox="-50 -50 100 100"
      width={size}
      height={size}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <defs>
        <mask id={`m${id}`} maskUnits="userSpaceOnUse" x="-50" y="-50" width="100" height="100">
          <rect x="-50" y="-50" width="100" height="100" fill="#fff" />
          <g fill="none" stroke="#000" strokeWidth={gap} strokeLinejoin="round">
            <path d={SPEAKING} />
            {TURNS.map((r) => (
              <path key={r} d={BLADE} transform={`rotate(${r})`} />
            ))}
          </g>
        </mask>
      </defs>
      <g mask={`url(#m${id})`}>
        <path d={SPEAKING} fill="var(--mark-speak)" />
        {TURNS.map((r) => (
          <path key={r} d={BLADE} transform={`rotate(${r})`} fill="var(--mark-blade)" />
        ))}
      </g>
    </svg>
  );
}
