# POC status

Last updated: 2026-09-27 (after local verification on the M4). Legend:

- **Implemented** — code exists and is exercised by automated tests (mocks/fixtures).
- **Simulated** — demonstrated end-to-end with replay/mock adapters only.
- **Hardware-verified** — run on the target Mac with the real camera/audio/remote. So far only the M4's software
  side (doctor, real ORF/JPEG decode, timings); camera/audio/remote not yet — docs/local-verification-results.md.
- **Model-evaluated** — measured with real providers on owner photos. *Nothing yet.*

The POC is **not validated** until one real tethered shoot completes with spoken coaching, PTT,
retake comparison and a coverage review (docs/hardware-checks.md §7).

## Milestones

| Milestone | Implemented | Simulated | Hardware-verified | Model-evaluated |
|---|---|---|---|---|
| M0 skeleton, persistence, replay, doctor | ✅ | ✅ replay survives restart (tests) | ✅ doctor on the M4 (arm64, ExifTool, `say`); permissions pending | n/a |
| M1 tethered capture + evidence UI | ✅ | ✅ partial writes, duplicates, late RAW, restart recovery | ⏳ 30-press gate | n/a |
| M2 first coaching loop | ✅ OpenAI + Gemini adapters, schema, repair, exposure helper | ✅ mock provider | n/a | ⏳ live smoke + offline eval |
| M3 speech + global PTT | ✅ `say`, sounddevice, transcription adapter, pynput tracker | ✅ mock speech/mic | ⏳ headphones, mic, PTT, remote | ⏳ transcription quality |
| M4 retake comparison + coverage | ✅ | ✅ 3/3 loops, stale suppression, keepers | ⏳ | ⏳ |
| M5 evaluation + decision | ✅ runner, rubric, report template | ✅ mock dry run | ⏳ | ⏳ decision pending |

## Feature detail

| Area | Status | Evidence / notes |
|---|---|---|
| Watch-folder ingestion (watchdog + periodic reconciliation) | Implemented, simulated | `tests/test_ingest.py`, replay `ingest_stress` |
| Stability policy (3×250 ms + full decode; bounded retry → pending_retry) | Implemented | truncated/partial write tests |
| Immutable hash-verified copies; originals untouched | Implemented | `test_originals_untouched_and_copies_read_only` |
| Hash dedupe of repeated events / re-saved files | Implemented | `test_duplicate_content_and_repeated_events` |
| RAW/JPEG pairing (stem + dir + EXIF time/detection time), late RAW without re-coaching | Implemented, simulated with a **fake** RAW | real ORF pending (hardware) |
| RAW-only preview (embedded → developed → clear failure) | Implemented, verified on a real ORF | LibRaw 0.22.1 decodes an E-M1 II ORF; embedded 3200×2400 preview in 39 ms (RAW-only captures are coached from it) |
| Metadata via ExifTool (Pillow fallback) | Implemented, verified on real files | ExifTool 13.55 on an E-M1 II ORF + JPEG: shutter, aperture, ISO, lens, program, flash, orientation, AF/IS/drive maker notes |
| Shot/setup snapshot at first detection, ambiguity flag, reassignment | Implemented | tests |
| Restart recovery (recovered captures never spoken; interrupted analyses failed) | Implemented | tests |
| Overview/crops orientation-normalized, region selection, measurements | Implemented | `test_imaging.py` |
| 20 MP local evidence time | Measured on the M4 | median 310 ms / max 396 ms on 12 real E-M1 II JPEGs; framing score ≤ 3 ms; zone masks 345–400 ms on first hover |
| Assessment schema (strict), semantic validation, one repair, visible failure | Implemented | `test_domain.py`, `test_coaching.py` |
| OpenAI Responses adapter | Implemented | shape re-checked against docs 2026-09-27; output budget raised for reasoning, optional effort; **no live call made** |
| Gemini adapter | Implemented | shape re-checked against docs 2026-09-27; thinking counted as output, budget raised, optional thinking level; **no live call made** |
| Claude adapter (Messages API: structured output, adaptive thinking, optional effort, server-side refusal fallback with serving model recorded) | Implemented | request shape vs installed `anthropic` 1.8 SDK; default model `claude-opus-5-5` (switched from `claude-opus-5` on 2026-09-27: Anthropic's recommended model, $4/$20 vs $5/$25 per MTok); **no live call made** |
| Model ids / prices | Documented, not yet configured on the Mac | checked 2026-09-27 from official docs: setup.md#models + `.env.example` (price block ready); keys not yet set |
| Deterministic exposure equivalence | Implemented | refuses flash / auto ISO / non-manual / changing light |
| Teaching prompts (every Nth coached capture) | Implemented | test |
| Stale speech suppression (shot switch, newer capture, PTT) + coalescing | Implemented, simulated | tests, replay `stale_switch` |
| Speech via macOS `say` (voice/rate/device, cancellable) | Implemented | **not run** (Linux build env) |
| Microphone capture (sounddevice) | Implemented | **not run** (no PortAudio/mic in build env) |
| Transcription (OpenAI) | Implemented | **no live call made**; mock in tests |
| PTT state machine (repeat ignore, empty clip, lost key-up timeout, toggle, cancel, interruption) | Implemented | `test_voice.py` (mock audio) |
| Global keys via pynput + diagnostics + learn key | Implemented | pure tracker tested; **listener not run on macOS** |
| Voice commands (repeat, next shot, explicit keeper phrase) | Implemented | tests |
| Offline behaviour (local features continue, spoken offline notice, no backlog replay) | Implemented | tests |
| Keeper decisions (explicit, linked, hash-verified), coverage, exports | Implemented | `test_coverage.py` |
| Experiment records + user rating/lesson | Implemented | UI + API |
| Timing marks + export; cost estimate when prices configured | Implemented | speech_process_started ≠ audible onset |
| Optimisation telemetry: raw model I/O per call (incl. invalid/failed), sub-stage timings, persisted events (speech outcomes, stop latency, PTT keys, network probes, startup snapshot), log file, JSONL export | Implemented | `test_telemetry.py`; docs/telemetry.md |
| Offline eval runner (split, bounded paid runs, stability, report) | Implemented | mock dry run only |
| Live teaching-trial summary | Implemented | no trial run |
| At-camera controls: received/failure cues, voice rating/lesson/change-note, pause/resume (voice, UI, remote key), per-session paid-call/USD cap | Implemented, simulated | `test_preshoot.py`; cues via `afplay` untested on macOS |
| `preflight` go/no-go and `inspect` (scrubbed camera-file report) commands | Implemented; `inspect` verified on a real ORF + JPEG | `inspect` now also scrubs local paths; `preflight` with real headphones/mic/keys **not run** |
| Running-apparel starter shot list (8 shots) | Implemented | criteria are starting points; tune after the first shoot |
| Plain-language histogram reading (rules, per region first), region histograms, lost-detail overlay, "what your retake changed" | Implemented, simulated | `test_histogram_insights.py`; overlay generated on demand (keeps it off the feedback latency path) |
| Session replay eval (recorded requests → other models/prompts; frozen/chained; agreement with session + keeper/experiment/post-hoc labels) | Implemented, simulated | `test_session_replay.py`; mock dry run only |
| Security: loopback, host/origin checks, ID-only file serving, import roots | Implemented | `test_api.py` |
| Redesigned frontend (Claude Design handoff, `docs/design/`): Shoot (shot rail, stage with regions, brightness inspector painting tonal zones on the photo, filmstrip, coach panel states incl. worse/mixed/can't-compare, keeper confirm/undo, voice bar), Coverage, Sessions/New shoot, Shot list editor, Setup with versions, Diagnostics; Studio + Daylight themes; bundled fonts; keyboard map | Implemented, simulated | Vitest (132) + Playwright (backend-served build, mock adapters); checked on the Air in Chromium + WebKit at 1470×956, both themes (docs/screenshots/); keyboard map verified; Esc/popover, Space-after-click and a Diagnostics layout bug fixed. **Real Safari and sunlight not yet**; region drawing is pointer-only |
| Framing match (layout + texture signature), comparison metrics (region deltas, relative sharpness, EV from EXIF for manual exposure), baseline candidates, attribution hints | Implemented, simulated | `test_framing.py`, `test_redesign_api.py`; threshold 0.65 calibrated on **synthetic** images only — recalibrate on real fabric close-ups with `scripts/framing_pairs.py` (docs/local-verification.md §6) |
| Cancel analysis, retry now / when online, re-read bad file, skip stuck file, typed questions (`/voice/text`), per-session theme | Implemented | `test_redesign_api.py` |
| Coloured `doctor` / `preflight` output | Implemented | `test_term.py`; honours NO_COLOR / FORCE_COLOR |

## Automated test results (mocks only)

On the M4 MacBook Air, 2026-09-27 (`./scripts/check.sh`):

- Backend: `uv run pytest` → 151 passed, 3 live (paid) tests deselected. `ruff check` clean.
- Frontend: `npm run typecheck` clean; `npm test` 137 passed; `npm run build` ok; `npm run e2e` 2 passed with
  Playwright's own Chromium
  (replay coaching loop → comparison → keeper → coverage; hold-to-talk → answer).

## Remaining gates (in order)

Start with docs/local-verification.md: it covers the checks the cloud build could not do (model ids and
prices from the official docs, macOS audio/keys, OM Capture file behaviour, the UI on the real screen,
M4 performance, framing calibration on real photos).


1. `aperture-ally doctor` on the M4: arm64, ExifTool, `say` ✅; microphone + Input Monitoring permissions pending.
2. Model ids + prices documented ✅ (setup.md#models); set keys in `.env`, then `uv run pytest -m live -s tests/test_live.py`.
3. M1 30-press ingestion gate (hardware-checks.md §1).
4. M3 speech / mic / PTT / remote (§3), incl. video-measured interruption and audible onset.
5. M2 three intentional real-provider examples (§2).
6. M4 three real loops + stale switch + coverage (§4).
7. Owner dataset (30–50), split, two-model offline eval (evals/README.md).
8. ~10-experiment live teaching trial (§6), then the validation shoot (§7); update docs/poc-report.md
   and make the proceed / revise / stop call.
