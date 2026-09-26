# Aperture Ally POC report

Status date: 2026-09-26. **Decision: not yet possible.** The software loop is implemented and verified
in simulation, but none of the evidence the decision depends on (real camera, real speech/PTT on the
target Mac, real model quality, live teaching trial) has been collected yet. Sections marked
*pending* must be filled in from the procedures in [hardware-checks.md](hardware-checks.md) and
[../evals/README.md](../evals/README.md). Do not read the simulated numbers as photographic evidence.

## 1. What was measured so far (simulated only)

Environment: Linux x86_64 container, 4 vCPU, Python 3.12.3 — **not** the target M4 MacBook Air. Mock
provider (`mock-heuristic-v1`, fixed 150 ms latency), mock speech, mock microphone/transcription.
Inputs: synthetic 2400×1600 fixtures written into the watch folder by the replay simulator.

### Replay `basic_loop` (2 runs)

| Check | Run 1 | Run 2 |
|---|---|---|
| Captures ingested / expected (duplicate dropped, late RAW paired) | 7/7 | 7/7 |
| Baseline → advice → retake → comparison loops completed | 3/3 | 3/3 |
| Mock comparison outcome for those loops | improved ×3 | improved ×3 |
| Spoken utterances (7 advice + 1 PTT answer), cancelled | 8, 0 | 8, 0 |
| Keepers accepted → coverage resolved | 3/6 | 3/6 |

The "improved ×3" is by construction: the mock compares measurements on fixtures designed to improve. It
proves the linkage (baseline selection, previous advice, user-reported change, experiment record), not
coaching quality.

### Pipeline timing (ms, n = 7 captures per run)

| Interval | Run 1 p50 / p95 | Run 2 p50 / p95 | Target (hypothesis) |
|---|---|---|---|
| file detected → file ready | 782 / 1729 | 778 / 1725 | — (policy-bound) |
| file ready → evidence (local feedback) | 285 / 381 | 196 / 257 | p95 < 1000 |
| model call (mock, fixed) | 151 / 151 | 151 / 152 | n/a |
| file ready → validated result | 456 / 539 | 354 / 419 | — |
| file ready → speech process started | 457 / 541 | 355 / 420 | median < 5000, p95 < 10000 *(real model)* |

- detected → ready is dominated by the stability policy (3 unchanged checks × 250 ms ≈ 750 ms after the
  last write) plus chunked replay writes (p95). It is configurable (`APERTURE_ALLY_STABILITY_*`); measure
  on hardware before tuning.
- Evidence for a **20 MP** JPEG (5184×3888, 5.4 MB) on this container: ~0.45 s after optimisation
  (was ~1.1 s). The M4 figure is pending.
- "speech process started" is not audible onset; Bluetooth output adds latency (measure by video).

### Automated tests

Backend: 79 tests pass (+2 paid live tests deselected by default). Frontend: see POC_STATUS.md. They
cover the plan's software risks; they are not camera/audio/model-quality trials.

### Offline eval harness dry run (mock, synthetic example set)

8 items, 2 repeated ×3: false acceptance 0/3, unnecessary retakes 0/5, criterion agreement 5 agree /
1 disagree / 1 model-uncertain (of 7), comparison 1/1, repeat stability 2/2. **Meaningless for quality**
(the mock's thresholds were tuned to these fixtures) — it only shows the runner and report work.

## 2. Hardware results — *pending*

| Gate | Result | Notes |
|---|---|---|
| M1: 30 presses → 30 captures, RAW+JPEG pairs, restart, reconnect | pending | `aperture-ally ingest-report --expect 30` |
| ORF metadata via ExifTool; RAW-only preview via LibRaw | pending | |
| M3: audible via Bluetooth headphones | pending | |
| M3: PTT while OM Capture foreground; hold/release/repeat | pending | |
| M3: interruption latency (video) | pending | target ≈ ≤300 ms |
| M3: lost-release timeout | pending | |
| M3: chosen remote (model, key, held vs pulse) | pending | no compatibility claim until tested |
| Shutter → file ready (video, n≥10) | pending | |
| File ready → first audible speech (video, n≥10) | pending | |

## 3. Model evaluation — *pending*

Fill from `evals/results/<run>/report.md` for two configurations on the owner dataset (dev and held-out
reported separately): false acceptance, unnecessary retakes, criterion agreement, uncertainty, stability,
invented context (manual review), tokens, cost, latency, errors. Record resolved model ids and prompt
version `coach-2026-09-26.1`.

## 4. Live teaching trial — *pending*

From `aperture-ally eval trial`: helpful x/10 (target ≥7), harmful x/10 (target ≤1), lessons recalled x/10,
plus notable failures in Drew's words.

## 5. Costs — *pending*

Tokens per assessment and estimated spend per shoot, from the timing export and eval report (prices
must be entered from official pricing pages; none were verifiable at build time).

## 6. Known limitations and unresolved failures

- Model identifiers, prices and current API limits could not be checked against official docs from the
  build environment (egress blocked). Request shapes were verified against the installed SDK types only.
- OM Capture menu names in setup.md are unverified for the installed version.
- No real ORF was available: RAW pairing/preview paths are tested with a fake RAW (unsupported path) and
  real JPEGs; LibRaw's handling of E-M1 II ORF is a hardware check.
- AdobeRGB JPEGs without an embedded ICC profile are treated as sRGB (the camera marks Adobe RGB via EXIF,
  not always an ICC profile) — colour of the overview may be off in that mode; shoot sRGB.
- Clipping is measured on the rendered JPEG; sharpness indicators are relative and only compared when
  region rectangles, pixel sizes and focal length match. Framing similarity is not verified.
- The mock provider is a threshold heuristic for replay/testing only.
- Global keys use pynput; untested on the target Mac. If Input Monitoring proves unreliable, a small
  native helper is the fallback (not built).
- Voice keeper acceptance only on the exact phrase "accept this photo as keeper" (tied to the photo
  snapshotted at key-down).
- Only one session is watched at a time.

## 7. Recommendation

Proceed to the hardware and evaluation gates **before** any further feature work or packaging:
M1 ingestion (30 presses) → M3 speech/PTT on the M4 → owner dataset + two-model offline eval → live
teaching trial → one validation shoot. Then decide proceed / revise / stop on: the ≥7/10 helpful
and ≤1/10 harmful hypotheses, false-acceptance counts, and whether first audible advice is fast enough
at the camera. If latency misses, fix the measured dominant stage first.
