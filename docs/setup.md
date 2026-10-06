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

Checked **2026-09-27** against the official docs (sources below). Ids and prices change; re-check before
relying on them, and copy prices into `APERTURE_ALLY_PRICES` (the commented block in `.env.example` is ready
to uncomment). Price keys must match the *resolved* model id shown on an assessment.

| Provider | Model id | Role | USD per 1M tokens (in / out) | Source |
|---|---|---|---|---|
| Claude | `claude-opus-5-5` | **default** (Anthropic's recommended starting model) | $4 / $20 | [pricing](https://platform.claude.com/docs/en/about-claude/pricing), [models](https://platform.claude.com/docs/en/about-claude/models/overview) |
| Claude | `claude-sonnet-5-5` | cheaper candidate to evaluate (released 2026-09-28; "fast"; default effort high) | $2 / $10 | same (checked 2026-09-28) |
| Claude | `claude-sonnet-5` | superseded by Sonnet 5.5 at the same price | $2 / $10 | same |
| Claude | `claude-opus-5` | previous default, still active | $5 / $25 | same |
| OpenAI | `gpt-6-sol` | suggested | $2 / $10 | [model page](https://developers.openai.com/api/docs/models/gpt-6-sol), [pricing](https://developers.openai.com/api/docs/pricing) |
| OpenAI | `gpt-6-luna` | cheaper | $0.10 / $0.50 | [model page](https://developers.openai.com/api/docs/models/gpt-6-luna) |
| OpenAI | `gpt-transcribe` | speech-to-text (recommended) | $0.0045 / minute | [model page](https://developers.openai.com/api/docs/models/gpt-transcribe), [guide](https://developers.openai.com/api/docs/guides/speech-to-text) |
| OpenAI | `gpt-4o-mini-transcribe` | cheaper speech-to-text | ≈ $0.003 / minute | [model page](https://developers.openai.com/api/docs/models/gpt-4o-mini-transcribe) |
| Gemini | `gemini-3.8-flash` | suggested (stable) | $0.75 / $3.75 until 2026-12-31, then $1.50 / $7.50 | [models](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| Gemini | `gemini-3.5-flash-lite` | cheaper (stable) | $0.30 / $2.50 | same |

Notes:

- **Claude.** Request shape re-checked against the docs and the installed `anthropic` 1.8.0 SDK: images as
  base64 `image` blocks, `output_config.format` JSON-schema structured output (GA), adaptive thinking,
  optional `output_config.effort` (`low|medium|high|xhigh|max`, GA), server-side refusal fallback
  (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`). If the classifiers decline, the fallback
  model answers in the same call; the answering model is recorded as `model_resolved` and
  `usage.fallback_used` is set. The default moved from `claude-opus-5` to `claude-opus-5-5` on 2026-09-27.
  Opus 5.5's API-default effort is **medium** (Opus 5's was high), so pin `APERTURE_ALLY_CLAUDE_EFFORT` when
  comparing. Thinking tokens are billed as output; adaptive thinking adds latency, so sweep effort with the
  session-replay harness before choosing a live setting. Images: ⌈w/28⌉×⌈h/28⌉ tokens, capped at 2576 px /
  4784 tokens per image on these models. Haiku 4.5 does not support adaptive thinking and would need adapter
  changes. Known limitation: when a request is declined and served by the fallback, only the serving
  attempt's tokens are counted.
- **OpenAI.** Responses API with `text.format={type: json_schema, strict: true}` and `input_image.detail`
  (`low|high|auto|original`; `auto` and `original` send full resolution on gpt-5.6-class models, ~28k tokens
  for a 24 MP frame, so keep `high`). Current models reason at **medium** effort by default and spend
  `max_output_tokens` on reasoning first; the adapter reserves 25 000 (it was 2000, which could return an
  `incomplete` response with no JSON). `APERTURE_ALLY_OPENAI_EFFORT` sets `reasoning.effort`. The vision
  guide's image-token tables list `gpt-5.6-terra`/`gpt-5.6-luna` but not the gpt-6 models; use those if
  exact image-cost accounting matters. openai.com/api/pricing was not reachable (HTTP 403); prices are from
  developers.openai.com.
- **Gemini.** `response_mime_type=application/json` + `response_json_schema`, per-image `media_resolution`
  (`low|medium|high|ultra_high` = 280/560/1120/2240 tokens per image on Gemini 3; per-image resolution is
  Gemini 3 only). Thinking tokens count against `max_output_tokens` and are billed as output; the adapter
  now counts them in `output_tokens` and reserves 16 000. `APERTURE_ALLY_GEMINI_THINKING_LEVEL` is optional
  (3.8-flash: low/medium/high, default medium; 3.5-flash-lite adds minimal, its default). Google now calls
  `generateContent` "legacy" in favour of the Interactions API but says it "remains fully supported".

At setup time:

1. Set `APERTURE_ALLY_OPENAI_MODEL`, `APERTURE_ALLY_GEMINI_MODEL`, `APERTURE_ALLY_TRANSCRIPTION_MODEL` (and keys).
2. Uncomment `APERTURE_ALLY_PRICES` in `.env`; otherwise cost shows "n/a" and the USD cap ignores those calls.
3. Run the paid smoke test once: `uv run pytest -m live -s tests/test_live.py` (a few calls per configured
   provider). Each assessment records the *resolved* model id and prompt version.

## 3. The camera: direct control (default) or OM Capture

**Direct control (default, `APERTURE_ALLY_CAMERA=direct`).** The app talks to the E-M1 Mark II over USB
(python-gphoto2): settings from the 8BitDo Micro, the shutter (A), live view (L), the coach's aperture (Y), and
photos (JPEG + ORF) downloaded straight into the shoot. Verified at the desk on 2026-10-05
(`docs/camera-control-runsheet.md`).

1. Quit OM Capture. Plug in USB, switch the camera on and choose the PC-control USB mode
   (**RAW/Control** on the E-M1 Mark II).
2. Open a shoot: the app takes the camera by itself ("connected in ~4 s"). The first photo of each connection
   takes ~10 s while the card is read; after that ~2 s from shutter to coaching.
3. While the app has the camera, its own buttons and dials work too.
4. **After quitting the app or releasing the camera (⌘K), unplug the camera and plug it back in** to use its
   own buttons. The camera locks them after any PC control (OM Capture's too); switching it off and on isn't
   enough after the app.
5. Sleep is fine: when the camera wakes, the app reconnects and live view comes back.

**OM Capture instead (`APERTURE_ALLY_CAMERA=off`, or ⌘K → Release).** Aperture Ally then only reads the files
OM Capture saves:

1. OM Capture → save settings: a dedicated folder, e.g. `~/Pictures/OMCapture/ApertureAlly`. If your version
   offers **save to PC and card**, enable it, so the SD card keeps a backup copy.
2. Image quality: **RAW+JPEG (LF+RAW)** recommended. JPEG drives coaching; RAW is paired and preserved.
   RAW-only works when LibRaw can extract/develop a preview; otherwise the capture is kept but flagged.
3. Create the shoot with **Watch folder** = that folder. Only files modified after the shoot was created are
   ingested.
4. Before switching the active shot in the UI, **wait for the "Received ✓ photo #N" indicator** for the
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

### Recommended remote: 8BitDo Micro (~$25)

In **keyboard mode** (slider on `k`) the Micro sends a real key-down while a button is held and key-up
on release, so hold-to-talk works (confirmed by others using it for push-to-talk dictation:
github.com/HarrisHan/8bitdo-micro-karabiner). Out of the box its buttons send ordinary letters (e.g.
`g`, `j`). Aperture Ally only *listens* to keys, so those letters would also be typed into whatever app is
in front (OM Capture). Remap the buttons to keys nothing else uses:

**Option A — no extra app (try first).** If 8BitDo's own software (8BitDo Ultimate Software) lets you
remap the Micro's keyboard-mode buttons, set L → F18 (talk), R → F17 (pause coaching), B → F16 (cancel).
Unverified: check it supports the Micro before relying on it.

**Option B — Karabiner-Elements (free).** It remaps only the Micro, so your own keyboard is untouched.
1. Install Karabiner-Elements and grant its permissions.
2. Open Karabiner-EventViewer and press each Micro button to see its `key_code`.
3. Karabiner → Complex Modifications → add this rule (fill in the key codes; the vendor/product IDs are
   from the repo above, so confirm them in EventViewer's device list):

```json
{
  "description": "8BitDo Micro → Aperture Ally (hold L = talk, R = pause coaching, B = cancel)",
  "manipulators": [
    { "type": "basic", "from": { "key_code": "<L button key>" }, "to": [{ "key_code": "f18" }],
      "conditions": [{ "type": "device_if", "identifiers": [{ "vendor_id": 11720, "product_id": 36897 }] }] },
    { "type": "basic", "from": { "key_code": "<R button key>" }, "to": [{ "key_code": "f17" }],
      "conditions": [{ "type": "device_if", "identifiers": [{ "vendor_id": 11720, "product_id": 36897 }] }] },
    { "type": "basic", "from": { "key_code": "<B button key>" }, "to": [{ "key_code": "f16" }],
      "conditions": [{ "type": "device_if", "identifiers": [{ "vendor_id": 11720, "product_id": 36897 }] }] }
  ]
}
```

Use buttons mapped one-to-one. Buttons used as Karabiner modifier layers (the repo's R/R2) add ~0.5 s
delay. Avoid `fn` as the talk key; macOS handles it specially.

Then set, in `backend/.env`:

```
APERTURE_ALLY_GLOBAL_KEYS=pynput
APERTURE_ALLY_PTT_KEY=f18
APERTURE_ALLY_PTT_MODE=hold
APERTURE_ALLY_PAUSE_KEY=f17
APERTURE_ALLY_CANCEL_KEY=f16
```

and run `uv run aperture-ally preflight`. Its push-to-talk step shows press → hold time → release and how
many auto-repeats were ignored. Karabiner (if used) and your terminal both need Input Monitoring.

Why not build this into the app? Doing it properly means reading the remote at the device level and
taking exclusive control of it (so its keys never reach other apps), plus handling sleep/reconnect.
That's native macOS work that can only be verified on your Mac. Worth it after the POC if a second app
proves annoying, not before.

## 6. At the camera: cues, voice commands, pausing, budget

**Before each shoot** run `uv run aperture-ally preflight` with the app stopped. It checks storage and
the watch folder, plays the received sound and a sentence (confirm you heard both *in the headphones*),
records and transcribes a test phrase, waits for a press-and-hold of your PTT key, probes the network, and
makes one real assessment per configured provider (a few cents). It ends with GO / NO-GO and saves a JSON
record under `~/ApertureAlly/preflight/`. `--no-paid`, `--skip-mic`, `--skip-keys` and `--yes` are available.

**Reading brightness.** Under the photo, the brightness inspector explains the histogram in plain
language, marked regions first, then the whole frame. Hover or click a zone (pure black, shadows,
mid-tones, highlights, pure white) and the matching pixels light up on the photo: solid red is pure white
and solid blue is pure black (no detail in either); the other zones get an accent tint. `H` toggles the
lost-detail overlay. After a retake the coach panel lists what changed ("Pure white on the trim
3.1% → 0.4%", "Logo +36% sharper", "Overall darker, mean 124 → 118 of 255"; EV only when both photos were
manual exposure). "Framing match" says whether the two photos are framed alike enough to compare; if not,
use "Compare with…" to pick another baseline. All of it describes the processed JPEG; the RAW file may
hold a little more detail.

**Studio and Daylight.** The dark Studio theme is for indoor shoots. Outdoors, switch to Daylight
(☀ in the top bar, or `D`): light surfaces, heavier type and a mid-grey mat around the photo so it isn't
judged against white. New shoot → "Outdoor" starts a session in Daylight. In sun, trust the numbers (pure
white %, the brightness headline) more than how the preview looks.

**Keys** (never while typing in a field): Space talk · R repeat · S stop · P pause/resume coaching ·
H lost detail · ← → previous/next photo · `[` collapse the shot list · ⌘↵ accept keeper ·
⌘R retry when the coach failed · Esc cancel/close · ⌘1–7 tabs (Library ⌘6, Diagnostics ⌘7) · ⌘N new shoot ·
N today's notes · ⌘I what the coach saw · ⌘, coaching & audio · ⌘⇧S save the shot list to its template ·
D Daylight · with direct camera control: L live view · Y apply the coach's suggestion · ⌘K take/release the camera.

**Received cue.** Every new photo plays a short sound (`APERTURE_ALLY_RECEIVED_CUE=sound`, the default,
which mixes with speech). Use `speech` to hear "Got 12" instead; it's skipped if the coach is talking.
A different sound means something failed (unreadable file, AI unavailable); the screen says what.

**Voice commands** (hold PTT and say):

| Say | Effect |
|---|---|
| "I moved the light a hand-width left" (starts with *I moved / changed / rotated / raised / lowered / …*, no question) | change note attached to the next photo of the active shot |
| "That helped" / "That didn't help" / "That made it worse" | rates the advice you just tried (helpful / neutral / harmful) on its experiment card |
| "Lesson: side light shows the mesh" (or "The lesson is …", "Note, …") | saves your own explanation on the experiment card |
| "Pause coaching" / "Be quiet" · "Resume coaching" | auto-coaching off/on; photos are still saved, and "Review #N anyway" still works |
| "Next shot" · "Repeat that" · "Accept this photo as keeper" | as before |
| anything else | a question for the coach about the current photo |

Rate and write lessons while they're fresh. They feed the teaching-trial numbers
(`aperture-ally eval trial`) that decide whether the POC works. You can edit them later on the cards.
`APERTURE_ALLY_PAUSE_KEY` can map a second remote button to pause/resume.

**Budget.** Each session stops auto-coaching after `APERTURE_ALLY_SESSION_MAX_MODEL_CALLS` paid
assessments/answers (default 150) or `APERTURE_ALLY_SESSION_BUDGET_USD` estimated spend (only counts
models with a configured price). When a cap is hit you hear it once, coaching pauses, and photos keep
arriving. Raise the cap from the Coaching pill in the top bar (or "Raise cap" in the coach panel), then resume. Transcription is never blocked,
so voice commands keep working. Mock sessions never count.

## 7. Replay mode

```bash
./scripts/dev.sh
cd backend && uv run aperture-ally replay basic_loop   # or ingest_stress / stale_switch
```

Replay writes synthetic images into the session watch folder like a camera would. The UI Sessions tab
can also run a scenario against the current session. Replay sessions are marked `simulated`.

## 8. Recovery

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
