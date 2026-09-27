# Plan: full support for in-camera brackets

Status: proposed (2026-09-27). The interim rule shipped in `918e166`: frames are tagged with
`exif.bracket = {kind, shot}` from the Olympus DriveMode maker note, and only shot 1 (the base exposure)
is auto-coached; later frames are kept, don't interrupt the base frame's advice, and can be reviewed by
hand. This plan turns a bracket into a first-class "set".

## What we know (evidence)

From the owner's library (454 E-M1 II ORFs, `~/Pictures/Lightroom Saved Photos`, read locally):

- ~74% of frames are **5-frame AE brackets**; all in aperture priority.
- **One shutter press per frame**, 2–10 s apart (not a burst). Timing can't define a set; the shot number can.
- Olympus AE order: **shot 1 = base, then −2, −1, +1, +2 steps** (e.g. 0, −1.3, −0.7, +0.7, +1.3 EV).
  EXIF `ExposureCompensation` includes the bracket offset (base −1.7 → frames −1.7, −3.0, −2.3, −1.0, −0.3).
- The frame count (3/5/7…) and step are **not** in the file as far as we've seen; only the shot number.
- DriveMode also marks WB, FL, MF, ISO, "AE Auto" and focus brackets (bit mask); focus bracketing is a
  different use (stacking) and stays out of scope except for grouping.

## Keeper model: both (owner, 2026-09-27)

Sometimes one frame of the set is the best result, sometimes merging the set (HDR) is. So a keeper can be
**a frame** or **the whole set**, and the coach suggests which:
- **Frame** when one frame keeps detail in every marked region without clipping ("Frame 3, −0.7 EV").
- **Merge** when no single frame does but the set covers the range: the darkest frame holds the
  highlights and the brightest the shadows ("No single frame holds both the toe and the heel shadow;
  merge the set"). Also say when even the set falls short ("−2 still clips the toe: add a −3 frame").
- The owner decides; Coverage resolves a shot to a frame or to all frames of a set, and exports list them.

## Design

### 1. Sets (backend, no model change)
- `BracketSet` derived at ingest and persisted on the capture: `bracket_set_id`, `bracket_index` (shot),
  `bracket_ev` (offset from the base frame's ExposureCompensation; for manual exposure, from the
  shutter/aperture/ISO triangle via `domain/exposure.py`).
- A set **opens** at shot 1 (or at the first frame with a higher shot number than the open set's last,
  if shot 1 was missed) and **closes** when: the next shot 1 arrives, the active shot changes, the shot
  number doesn't increase, or no frame arrives for `bracket_idle_close_s` (default 30 s, since
  presses are manual). The expected size is learned from the previous closed set in the session.
- Recovered/late frames join their set by shot number + DateTimeOriginal ordering.
- Late RAWs pair with their JPEG as today; set membership follows the JPEG.

### 2. Coaching
- **Immediately on the base frame:** as now (fast spoken advice; latency unchanged).
- **When the set closes: a local, free "which frame" summary.** Per frame and per marked region: pure
  white %, pure black %, mean, sharpness (all already computed in evidence). Pick the frame that keeps
  the most detail in the marked regions without clipping; say it in one line ("Frame 3, −0.7 EV,
  keeps the mesh; base clips 3.1% on the toe"). No model call.
- **Optional model call per set** (setting, off by default): the base overview + the chosen frame's
  crops + a per-frame measurement table; the schema gains `bracket_choice {frame, reason}`. Bump
  `PROMPT_VERSION`; add bracket cases to the offline eval before enabling.
- The same summary decides frame vs merge (above): per region, is there one frame that holds it, and does
  one frame hold all regions?

### 3. Comparison and experiments
- Retake comparison is **set to set**: base vs base for "what changed"; plus the chosen frame of each set.
- `default_baseline` uses the previous set's base frame (already true with the interim rule, since only
  base frames get coached).
- An experiment links sets, not frames, when both sides are sets.

### 4. UI
- Filmstrip: one stacked thumb per set with an "AE ×5" badge; expand to show frames labelled by EV.
- Coach panel on a set: base-frame verdict + the "which frame" line; a frame strip (−2 … +2) that
  switches the photo, with brightness inspector per frame; "Compare frames" shows base vs chosen.
- Keeper: "Accept frame 3" or "Accept set (merge)", with the coach's suggestion pre-selected.
- Coverage/exports: keeper frame plus "from AE ×5 set #12", or all frames of a merge set (listed in
  order with EV); contact sheet shows the chosen frame or the base frame marked "merge ×5".

### 5. Tests and replay
- Unit: set open/close rules (missed shot 1, idle close, shot switch, interleaved late RAW, recovered).
- Unit: EV offsets from ExposureCompensation and from the exposure triangle.
- Replay scenario `bracket_loop`: two 5-frame sets with fixture JPEGs carrying synthetic bracket metadata
  (injected in the replay manifest, since synthetic JPEGs can't carry Olympus maker notes), a retake, a
  keeper; e2e asserts one spoken advice per set and the set-level summary.
- Hardware: owner step — shoot 3 sets tethered; check grouping, summary, keeper.

## Tasks (in order)

1. (done) Keeper model: frame or set.
2. Set derivation + persistence + API fields (backend, tests).
3. Local "which frame" summary + event + speech line (backend, tests).
4. Set-to-set comparison and experiment linkage (backend, tests).
5. Filmstrip stack, frame strip, set keeper (frontend, Vitest).
6. `bracket_loop` replay + e2e.
7. Optional per-set model call + prompt/schema bump + eval cases (behind a setting).
8. Hardware check with the owner; update POC_STATUS.

Estimated size: tasks 2–6 are a few days of focused work; task 7 is separate and gated on eval results.
