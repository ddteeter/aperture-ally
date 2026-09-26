# Setup on a fresh Mac (M4 MacBook Air)

Everything below runs natively on arm64. No Docker. Commands assume the repo is at `~/aperture-ally`.

## 1. Tools

```bash
xcode-select --install                       # command line tools (git, compilers)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install exiftool node                   # ExifTool for ORF/maker-note metadata; Node for the UI
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12                       # native arm64 CPython; do NOT run under Rosetta
cd ~/aperture-ally/backend && uv sync --frozen
cd ../frontend && npm ci && npm run build
cd ../backend && uv run aperture-ally doctor
```

`doctor` must show `arm64 native ✔`. If it shows x86_64 you are in a Rosetta terminal or an Intel
Python — fix before continuing (native wheels for OpenCV, rawpy and PortAudio are arm64).

## 2. Configuration

```bash
cp backend/.env.example backend/.env         # then edit
```

The backend reads `backend/.env` and the environment. Secrets are never sent to the browser, never
logged, and `doctor`/Diagnostics only report whether a key is *present*.

### Keys without writing them to disk (optional)

```bash
security add-generic-password -a "$USER" -s aperture-ally-openai -w      # prompts for the key
export OPENAI_API_KEY="$(security find-generic-password -a "$USER" -s aperture-ally-openai -w)"
```

### Models {#models}

**Claude** (added later) ships with a default: `claude-opus-5`, taken from Anthropic's bundled API reference
(cached 2026-06-24). Its request shape was verified against the installed `anthropic` SDK (1.8.0). It sends
images as base64 `image` blocks, uses `output_config.format` JSON-schema structured output and adaptive
thinking, and has an optional `APERTURE_ALLY_CLAUDE_EFFORT`. Server-side refusal fallback
(`fallbacks: "default"`) is on by default: if Claude's safety classifiers decline a request, Anthropic's
recommended fallback model answers in the same call. The answering model is recorded as `model_resolved`,
and `usage.fallback_used` is set. Opus-tier list prices in that reference were $5 / $25 per 1M input/output
tokens; confirm them before adding them to `APERTURE_ALLY_PRICES`. Thinking tokens count as output tokens,
and adaptive thinking adds latency, so sweep effort (`low`/`medium`/`high`) with the session-replay harness
before choosing a live setting.

For OpenAI and Gemini:

Model identifiers and prices change often and were **not verifiable from the build environment**
(the provider documentation sites were not reachable), so none are hard-coded. At setup time:

1. Open the official docs (OpenAI: images-vision + structured-outputs; Gemini: image-understanding +
   structured-output; OpenAI speech-to-text) and pick a **current vision model that supports JSON-schema
   structured output** for each provider, and a transcription model.
2. Set `APERTURE_ALLY_OPENAI_MODEL`, `APERTURE_ALLY_GEMINI_MODEL`, `APERTURE_ALLY_TRANSCRIPTION_MODEL`.
3. Optionally add prices to `APERTURE_ALLY_PRICES` with `verified_on` + `source_url`; otherwise cost shows "n/a".
4. Run the paid smoke test once: `uv run pytest -m live -s tests/test_live.py` (one synthetic image per
   configured provider). Each assessment records the *resolved* model id and prompt version.

Request shapes were verified against the installed SDKs (`openai` 3.19, `google-genai` 2.25): OpenAI
Responses API with `text.format={type: json_schema, strict: true}` and `input_image.detail`
(`low|high|auto|original`); Gemini `response_json_schema` with per-image `media_resolution`.

## 3. OM Capture (tethering)

OM Capture is the **only** program that talks to the camera. Aperture Ally never opens the USB device; it
only reads the files OM Capture saves.

> The OM System site could not be reached while writing this, so menu names below are from general
> knowledge of OM Capture — confirm them in your installed version and correct this page.

1. Install OM Capture for macOS from the OM System download page; confirm E-M1 Mark II is listed as
   supported and that your macOS version is supported.
2. Camera: set the USB connection mode to the tethering/PC-control mode (on the E-M1 Mark II this is
   offered as **RAW/Control** when the cable is connected, or via the custom menu USB mode setting).
3. OM Capture → save settings: choose a dedicated folder, e.g. `~/Pictures/OMCapture/ApertureAlly`.
   If your version offers **save to PC and card**, enable it, so the SD card keeps a backup copy.
4. Image quality: **RAW+JPEG (LF+RAW)** recommended. JPEG drives coaching; RAW is paired and preserved.
   RAW-only works when LibRaw can extract/develop a preview; otherwise the capture is kept but flagged.
5. In Aperture Ally (Sessions tab) create a session with **Watch folder** = that folder. Only files
   modified after the session was created are ingested; older files in the folder are ignored.
6. Before switching the active shot in the UI, **wait for the "Received ✓ photo #N" indicator** for the
   last frame. Captures detected within ~3 s of a shot switch are flagged *ambiguous* and can be reassigned.

## 4. Headphones and microphone

- **Output:** pair the Bluetooth headphones in macOS. Either make them the system output, or set
  `APERTURE_ALLY_SAY_AUDIO_DEVICE` to a name/ID from `say -a '?'`. Choose a voice with
  `say -v '?'` → `APERTURE_ALLY_SAY_VOICE`.
- **Input:** `APERTURE_ALLY_RECORDER=sounddevice`. Pick the microphone with `APERTURE_ALLY_INPUT_DEVICE`
  (names listed by `doctor`). Note: using a Bluetooth headset's microphone usually switches it to a
  low-quality call profile, which also degrades playback. A Mac/USB microphone with Bluetooth
  headphones for output is often better — test both (hardware-checks.md §3).
- Grant **Microphone** permission to the terminal app that runs the backend (macOS prompts on first use).
- Transcription: `APERTURE_ALLY_TRANSCRIBER=openai` plus a transcription model. Audio stays in memory and
  is discarded after transcription unless `APERTURE_ALLY_KEEP_VOICE_AUDIO=true`.

## 5. Push-to-talk and the Bluetooth remote

- **In the browser** (always available): hold the big *Hold to talk* button, or hold **Space** while the
  page has focus (not in a text field). **Esc** cancels speech/recording. Tick *toggle mode* for
  click-to-start/click-to-stop.
- **Global key** (works while OM Capture is in front): `APERTURE_ALLY_GLOBAL_KEYS=pynput`,
  `APERTURE_ALLY_PTT_KEY=…`. macOS requires **Input Monitoring** (and on some versions **Accessibility**)
  permission for the terminal app running the backend: System Settings → Privacy & Security →
  Input Monitoring → add/enable Terminal (or iTerm), then restart the backend. `doctor` reports both.
- **Find your remote's key:** Diagnostics tab → *Learn key* → press the remote button once; use the
  shown name (e.g. `page_down`, `f18`, `ctrl+f13`). Pick a key no other app reacts to (OM Capture may
  map arrows/space). Diagnostics shows press/release/repeat/hold time for the PTT key only; other
  keystrokes are never logged.
- Remotes that only send a momentary pulse (no held key state) need `APERTURE_ALLY_PTT_MODE=toggle`.
- Safety: a recording stops after `APERTURE_ALLY_PTT_MAX_SECONDS` (default 60) even if the key-up is lost,
  and is discarded (fail-closed). If the key listener dies, any active recording is cancelled.

## 6. Replay mode

```bash
./scripts/dev.sh
cd backend && uv run aperture-ally replay basic_loop   # or ingest_stress / stale_switch
```

Replay writes synthetic images into the session watch folder like a camera would. The UI Sessions tab
can also run a scenario against the current session. Replay sessions are marked `simulated`.

## 7. Recovery

- **Restart anytime.** State lives in `~/ApertureAlly/aperture_ally.sqlite3` plus files under
  `~/ApertureAlly/sessions/<id>/` (originals are read-only copies; evidence and exports alongside).
- On start, the active session's watch folder is re-scanned: photos taken while the app was stopped are
  ingested as **recovered** (never auto-coached, never spoken, attribution flagged for confirmation).
  Analyses interrupted by the shutdown are marked failed; use *Retry* to re-run them.
- **No network:** ingestion, measurements, shot list, keepers and coverage keep working; assessments fail
  with "AI unavailable". Nothing replays automatically when the connection returns — retry explicitly.
- **Transfer stuck** (`pending_retry` in the file list): the file never became stable/decodable. It is
  retried by the periodic scan; if OM Capture wrote a broken file, re-import from the SD card via the
  Sessions tab upload or `POST /api/sessions/{id}/imports` (paths under `APERTURE_ALLY_IMPORT_ROOTS`).
- **Wrong shot on a photo:** open it, *Reassign shot*. Assessments already made stay with their original
  context; request *Review again* to re-assess for the new shot.
- Reset everything: stop the app and move `~/ApertureAlly` away (it contains your photos — don't delete blindly).
