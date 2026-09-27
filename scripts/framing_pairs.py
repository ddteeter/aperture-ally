"""Score framing match on real photo pairs, through the same path the app uses.

    cd backend && uv run python ../scripts/framing_pairs.py pairs.csv

pairs.csv (no header): case,label,photo_a,photo_b — case is a|b|c|d from docs/local-verification.md §6
(a light moved, b small nudge, c zoomed/reframed, d different garment). Photos are read in place and
never copied into the repo; evidence goes to a temp dir. Prints a Markdown table and a threshold hint.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import time
from pathlib import Path

from aperture_ally.imaging import framing
from aperture_ally.imaging.evidence import build_evidence

EXPECT = {"a": "comparable", "b": "comparable", "c": "not comparable", "d": "not comparable"}


def main(csv_path: str) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="aa-framing-"))
    cache: dict[Path, dict] = {}

    def evidence(p: Path) -> dict:
        if p not in cache:
            cache[p] = build_evidence(p, tmp / str(len(cache)), [])
        return cache[p]

    rows = []
    with open(csv_path, newline="") as f:
        for case, label, a, b in csv.reader(f):
            pa, pb = Path(a).expanduser(), Path(b).expanduser()
            ea, eb = evidence(pa), evidence(pb)
            framing._score_cache.clear()
            t0 = time.perf_counter()
            m = framing.framing_detail(ea, eb)
            ms = (time.perf_counter() - t0) * 1000
            rows.append((case.strip().lower(), label, pa.name, pb.name, m.score if m else None, m.basis if m else "-", ms))

    print(f"| case | label | A | B | score | basis | ms | expected | at {framing.COMPARABLE} |")
    print("|---|---|---|---|---|---|---|---|---|")
    for case, label, a, b, score, basis, ms in rows:
        verdict = "-" if score is None else ("comparable" if score >= framing.COMPARABLE else "not comparable")
        ok = "✓" if verdict == EXPECT.get(case) else "✗"
        print(f"| {case} | {label} | {a} | {b} | {score} | {basis} | {ms:.1f} | {EXPECT.get(case, '?')} | {verdict} {ok} |")

    same = [r[4] for r in rows if r[0] in "ab" and r[4] is not None]
    diff = [r[4] for r in rows if r[0] in "cd" and r[4] is not None]
    if same and diff:
        lo, hi = min(same), max(diff)
        print(f"\nsame-framing min {lo:.3f} · different-framing max {hi:.3f} · current threshold {framing.COMPARABLE}")
        if lo > hi:
            print(f"separable; a midpoint threshold would be {(lo + hi) / 2:.2f}")
        else:
            print("overlap: no single threshold separates these pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
