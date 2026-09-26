# Telemetry for optimisation

Everything is recorded locally (SQLite + a log file under the data dir, default `~/ApertureAlly`) and is
git-ignored. It contains private shoot data: shot notes, transcripts, model outputs and file paths.

## Getting the data out

```bash
cd backend
uv run aperture-ally export --session <id-prefix>     # or Coverage tab → Export
```

This writes `sessions/<id>/exports/`:

| File | What |
|---|---|
| `timing.md` / `timing.json` | p50/p95/max per pipeline interval, ingest and evidence sub-stages, assessment sub-stages, model calls by purpose/model/attempt, speech outcomes and stop latency, voice-turn timings, PTT key hold times, network probes, failures |
| `telemetry/*.jsonl` | raw tables, one JSON object per line: `captures`, `assessments`, `model_calls`, `voice_turns`, `experiments`, `keepers` (incl. revoked), `shots`, `setup_revisions`, `source_files`, `timing_marks`, `events` |
| `coverage.*`, `contact_sheet.jpg` | shot coverage |

Load with pandas/DuckDB, e.g. `duckdb -c "select purpose, status, median(latency_ms) from 'model_calls.jsonl' group by all"`.
Join on `capture_id`, `assessment_id`, `voice_turn_id`. `mono_ns` values are only comparable within one `boot_id`.

The server log is at `<data dir>/logs/aperture-ally.log` (rotating, 10 MB × 5). It also has one line per app event.

The recorded model calls also drive **session replay evaluation**: resend a real shoot's exact requests
to other models or prompts (`aperture-ally eval session`, see [../evals/README.md](../evals/README.md) §3).

## What is recorded

**Per capture** (`captures.timings`):
- `file_age_at_first_stat_ms`: how old the file was when the app first saw it, which shows notification lag.
- `stability_wait_ms`, `stability_polls`, `stability_size_changes`, `stability_decode_failures`.
- `hash_ms`, `metadata_ms`, `copy_ms`, `raw_copy_ms`, `pair_wait_ms`, `raw_preview_ms`, `source_bytes`.
- `evidence.*`: decode/orientation/colour, overview + thumbnail, auto region, crops + region stats, global stats, executor queue wait, total.

Timing marks: file detected → ready → evidence ready → model request/response → validated → speech requested → speech process started → completed.

**Per assessment** (`assessments.timings`): queue wait for a model slot, evidence, baseline evidence, request build, model, repair, total, speech call duration and spoken words. Also `model_call_ids`, usage, cost and warnings.

**Per provider call** (`model_calls`), whether the call succeeded, was invalid or failed:
- purpose (assess / answer / transcribe), attempt (0 first, 1 repair), provider, requested and resolved model, prompt version;
- the full request: instructions, context JSON exactly as sent, schema hash, provider options (image detail / media resolution, max tokens), and per-image role, region, label, path, bytes and dimensions. Image bytes themselves are not duplicated;
- the **raw response text**, response id, usage (incl. reasoning tokens), latency, queue wait;
- status `ok | invalid | error | unavailable | timeout | cancelled`, validation errors and warnings, error text;
- the latest network probe at the time.

**Per voice turn**: clip duration, loudness (RMS) and bytes; transcriber and model; transcription and answer call ids; answer provider, model and usage; whether pixels were sent; whether the photo was older; wait for an in-flight assessment; release → speech-request time; speech duration and outcome.

**Events** (`telemetry_events`): every app event (capture.*, analysis.*, coach.speech.*, voice.*, shot.*, session.*, experiment.*), plus:
- `audio.speech`: kind, status (spoken / suppressed before request or before playback / cancelled / error), words, request → process-start time, played ms, stop reason;
- `audio.stop`: reason (`ptt`, `cancel`, `obsolete`, `preempted`, `user`), stop latency, how long it played before stopping;
- `keys.event` / `keys.listener`: press, release and repeat with hold ms for the configured PTT and cancel keys only. Other keystrokes are never recorded;
- `network.probe`: default-route interface and hardware port (no SSID), DNS and TCP connect time to each configured provider host. Runs every 5 min and right after a timeout or unavailable error;
- `app.started`: platform, package versions, schema version, public config (no secrets), adapters in use.

## Not measurable in software

- **Shutter → file written, and audible speech onset** (Bluetooth adds output latency after `speech_process_started`). Measure both by video; see hardware-checks.md §5.
- **True time-to-first-token.** Calls aren't streamed, so only total call latency is recorded.

## Switches

- `APERTURE_ALLY_STORE_MODEL_IO=false`: keep call metadata and latency, drop the request context and raw output.
- `APERTURE_ALLY_NETWORK_PROBE_INTERVAL_S=0`: no periodic probes.
- `APERTURE_ALLY_LOG_TO_FILE=false`: console logging only.
- `APERTURE_ALLY_KEEP_VOICE_AUDIO=true`: keep WAVs of PTT utterances (off by default).
