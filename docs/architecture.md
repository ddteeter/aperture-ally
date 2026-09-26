# Architecture

Single-user, local-first. One Python process (FastAPI + asyncio) serves the REST/WebSocket API and the
built React UI on `127.0.0.1:8765`. No broker, no Docker; blocking image work runs on a bounded thread
pool, SQLite on a dedicated single DB thread.

```
OM Capture ──writes──▶ watch folder ──watchdog hints + periodic scan──▶ IngestService
                                                                          │ stability + decode check
                                                                          │ sha256 dedupe, RAW/JPEG pairing
                                                                          │ immutable copy → sessions/<id>/originals/
                                                                          ▼
                                             evidence (overview, crops, measurements)  ──▶ capture.ready (WS)
                                                                          ▼
                              CoachingService (auto queue: newest wins; user reviews separate)
                               prompt + images ──▶ Provider adapter (mock | OpenAI | Gemini)
                               ◀── JSON ── validate (schema + semantics) → 1 repair → fail visibly
                               exposure helper (deterministic) · experiment linkage
                                                                          ▼
                              AudioController (one output stream; guard re-checked before playback)
                                                                          ▲
 Bluetooth remote / keyboard ──pynput──▶ PTT tracker ──▶ VoiceController (listen → transcribe → answer)
 Browser button / Space ──────REST──────────────────────┘
```

## Modules (`backend/aperture_ally/`)

| Package | Responsibility |
|---|---|
| `domain/` | Pydantic records (`models.py`), the assessment contract + validation (`assessment.py`), exposure helper |
| `persistence/` | SQLite schema migrations (`PRAGMA user_version`), `Store` (sync) and `AsyncStore` (DB thread) |
| `ingest/` | watcher, reconciliation, stability, dedupe, pairing, immutable copy, snapshots, import/upload |
| `imaging/` | ExifTool process + Pillow fallback, orientation/sRGB, overview/crops, measurements, RAW previews |
| `coaching/` | prompt (versioned), provider adapters, scheduling, validation/repair, experiments, Q&A |
| `audio/` | speech adapters (`say`/mock), AudioController, recorder/transcriber adapters, VoiceController |
| `input/` | global key listener (pynput) + pure `PTTKeyTracker` |
| `telemetry/` | stage timing marks (wall + monotonic), summaries, exports |
| `runtime.py` | in-memory current context per session → speech guards |
| `coverage.py` | keeper decisions (hash-verified), coverage states, JSON/Markdown/contact sheet |
| `replay.py`, `fixtures_gen.py` | simulated camera + synthetic fixtures |
| `services.py` | app container, session/shot/setup operations |
| `api/routes.py`, `app.py`, `cli.py`, `doctor.py` | HTTP/WS surface, factory, commands, checks |

All external dependencies sit behind small adapters (`Provider`, `SpeechBackend`, `Recorder`,
`Transcriber`, `MetadataReader`, key listener) and can be replaced independently.

## State axes

- **Capture processing:** discovered → stabilizing (ingest ledger `source_files`) → ready → analyzing →
  analyzed | failed | pending_retry.
- **Shot coverage:** missing → candidate → accepted; needs_retake is explicit (user flag or latest AI
  verdict). AI can make candidate/needs_retake, **never** accepted. Accepted = active `KeeperDecision`
  whose file hash still verifies.
- **Audio/voice:** idle, listening, transcribing, preparing_response, speaking, cancelled, error.

## Context, staleness and speech

`ContextTracker` keeps, per session: active shot, newest ready capture per shot, a voice epoch and a
user-request epoch. Every speech request carries a guard closure:

| Job | Speaks only if (re-checked immediately before playback) |
|---|---|
| automatic advice | shot still active **and** capture still newest for that shot **and** no PTT since |
| explicit review | no newer explicit review **and** no PTT since |
| voice answer | no newer PTT press/cancel (answers about older photos stay valid and say so) |

`AudioController` enforces one output stream (newest valid speech preempts), and `invalidate()` stops
current speech when a new capture arrives or the shot changes. Superseded results are stored with
`speech_status=suppressed`. Queued automatic requests are coalesced (newest wins); running ones finish
for history. Nothing is replayed after an outage.

## Attribution snapshot

At first detection of a file, the active shot, setup revision, ambiguity (shot switched < 3 s earlier),
recovered flag and the pending "what I changed" note are written to the ingest ledger. The capture is
created from that snapshot even after a restart; switching shots later never relabels it (explicit
reassignment only).

## Assessment contract

`AssessmentResult` (Pydantic, `extra=forbid`) → strict JSON Schema (all properties required, nullable via
`anyOf` null, refs inlined). Semantic validation rejects invented region ids, missing/unknown criteria,
comparison without (or with the wrong) baseline, unrequested teaching prompts, over-long speech and
metadata citations when no metadata exists; warnings flag stated camera settings without exposure
metadata. One repair attempt, then a recoverable failure. `exposure_target` lets the model request an
aperture/ISO change; the shutter equivalent is computed deterministically and only when the light is
continuous, controls are manual/known, and no flash fired.

## Security

Loopback bind (CLI refuses otherwise), `TrustedHostMiddleware` (DNS-rebinding), CORS + WebSocket
origin allowlist, images served only by capture ID from inside the session root, manual path imports
restricted to configured roots, uploads restricted to image types, secrets only in the backend
environment and never serialized.

## Persistence

`~/ApertureAlly/aperture_ally.sqlite3` (WAL). Tables: sessions, setup_revisions, shots, captures,
source_files (ingest ledger), assessments, experiments, keeper_decisions, voice_turns, timing_marks.
Each record table has indexed columns + a JSON body validated on read. New migrations are appended to
`MIGRATIONS`; never edit a released one.
