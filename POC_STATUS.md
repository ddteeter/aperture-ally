# POC status

Last updated: 2026-09-26. Legend:

- **Implemented** — code exists and is exercised by automated tests (mocks/fixtures).
- **Simulated** — demonstrated end-to-end with replay/mock adapters only.
- **Hardware-verified** — run on the target Mac with the real camera/audio/remote. *Nothing yet.*
- **Model-evaluated** — measured with real providers on owner photos. *Nothing yet.*

The POC is **not validated** until one real tethered shoot completes with spoken coaching, PTT,
retake comparison and a coverage review (docs/hardware-checks.md §7).

## Milestones

| Milestone | Implemented | Simulated | Hardware-verified | Model-evaluated |
|---|---|---|---|---|
| M0 skeleton, persistence, replay, doctor | ✅ | ✅ replay survives restart (tests) | — | n/a |
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
| RAW-only preview (embedded → developed → clear failure) | Implemented | LibRaw on real ORF **unverified** |
| Metadata via ExifTool (Pillow fallback) | Implemented | ExifTool not installed in build env; ORF tags **unverified** |
| Shot/setup snapshot at first detection, ambiguity flag, reassignment | Implemented | tests |
| Restart recovery (recovered captures never spoken; interrupted analyses failed) | Implemented | tests |
| Overview/crops orientation-normalized, region selection, measurements | Implemented | `test_imaging.py` |
| 20 MP local evidence time | Simulated | ~0.45 s on 4-vCPU x86 container; M4 pending |
| Assessment schema (strict), semantic validation, one repair, visible failure | Implemented | `test_domain.py`, `test_coaching.py` |
| OpenAI Responses adapter | Implemented | request shape vs installed SDK (`test_providers.py`); **no live call made** |
| Gemini adapter | Implemented | request shape vs installed SDK; **no live call made** |
| Model ids / prices | **Not configured** | docs unreachable from build env; must be set from official docs |
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
| Session replay eval (recorded requests → other models/prompts; frozen/chained; agreement with session + keeper/experiment/post-hoc labels) | Implemented, simulated | `test_session_replay.py`; mock dry run only |
| Security: loopback, host/origin checks, ID-only file serving, import roots | Implemented | `test_api.py` |
| Frontend (Shoot / Coverage / Diagnostics / Sessions): viewer, region drawing, histogram, before/after, coach card, experiment card, keeper confirm, hold/toggle/Space PTT, diagnostics, exports | Implemented, simulated | Vitest + Playwright (backend-served build, mock adapters); dev-server proxy path not e2e-tested; region drawing is pointer-only |

## Automated test results (build environment, mocks only)

- Backend: `uv run pytest` → 98 passed, 2 live (paid) tests deselected. `ruff check` clean.
- Frontend: `npm run typecheck` clean; `npm test` 33 passed; `npm run build` ok; `npm run e2e` 2 passed
  (replay coaching loop → comparison → keeper → coverage; hold-to-talk → answer).

## Remaining gates (in order)

1. `aperture-ally doctor` on the M4: arm64, ExifTool, `say`, microphone, permissions.
2. Configure model ids (+ prices) from official docs; `uv run pytest -m live -s tests/test_live.py`.
3. M1 30-press ingestion gate (hardware-checks.md §1).
4. M3 speech / mic / PTT / remote (§3), incl. video-measured interruption and audible onset.
5. M2 three intentional real-provider examples (§2).
6. M4 three real loops + stale switch + coverage (§4).
7. Owner dataset (30–50), split, two-model offline eval (evals/README.md).
8. ~10-experiment live teaching trial (§6), then the validation shoot (§7); update docs/poc-report.md
   and make the proceed / revise / stop call.
