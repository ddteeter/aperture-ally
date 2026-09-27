# Local verification handoff (run on the M4 MacBook Air)

The cloud build environment was Linux x86_64 with no camera, no audio devices, no macOS APIs and
no access to provider documentation sites. Everything below is untested there. Work through it on
the Mac, fix what is clearly a bug, and record every result in
`docs/local-verification-results.md` (create it). The results file is the deliverable: for each item give
PASS / FAIL / BLOCKED, what you ran, the evidence (numbers, error text, screenshot names) and any fix
commit.

Ground rules:

- Branch `claude/hopeful-goldberg-uele3r`. Commit fixes in small commits and push to that branch.
- Never commit API keys, `.env`, session databases, private photos, voice recordings or paid-call
  outputs (they are git-ignored; keep it that way). Screenshots of the UI are fine under `docs/screenshots/`.
- **Paid API calls only with the owner's explicit go-ahead in the chat**, with a small cap, and say
  roughly what they will cost first. Mock mode covers everything else.
- Don't claim photography reliability from software tests. "Works" here means the plumbing works.
- Read `POC_STATUS.md`, `docs/setup.md` and `docs/hardware-checks.md` first. Items that need the camera,
  headphones or remote in hand: prepare everything, then hand the owner exact steps and wait.

## 0. Baseline on macOS arm64

1. `uv --version`, `node --version` (20+), `brew list exiftool` (install if missing).
2. `./scripts/check.sh` — backend pytest + ruff, frontend typecheck + Vitest + build. Then
   `cd frontend && npx playwright install chromium && npm run e2e` (the sandbox used a
   different Chromium; this is the first run with Playwright's own browser).
3. `cd backend && uv run aperture-ally doctor` — expect arm64 native, ExifTool found, `say` found. Check
   the new coloured output is readable in Terminal/iTerm (green OK, yellow WARN, red FAIL) and that
   `NO_COLOR=1` and piping to `cat` give plain text.
4. Record `uv run python -c "import platform, cv2, rawpy; print(platform.machine(), cv2.__version__, rawpy.libraw_version)"`.

## 1. Model ids, prices and API shapes (provider docs were blocked in the cloud)

Nothing for OpenAI or Gemini is defaulted; Claude defaults to `claude-opus-5` from a bundled reference
dated 2026-06-24. From the official docs (not memory) determine and record:

- **Anthropic** (docs.claude.com / platform.claude.com): is `claude-opus-5` current and the right default
  for per-photo coaching (vision + structured output)? Current input/output price per MTok. Confirm
  the adapter's request shape still matches: `client.beta.messages.create` with
  `thinking={"type":"adaptive"}`, `output_config={"format": {json_schema…}, "effort": …}`, and the refusal
  fallback `fallbacks: "default"` with beta `server-side-fallback-2026-07-01`
  (`backend/aperture_ally/coaching/providers/claude_adapter.py`). Also consider whether a cheaper model
  or lower effort is a sensible alternative to evaluate (don't change the default without evidence).
- **OpenAI**: a current vision model id that supports the Responses API with `text.format` json_schema
  (strict) and `input_image` with `detail` (`openai_adapter.py`); the valid `detail` values; a current
  speech-to-text model id for `APERTURE_ALLY_TRANSCRIPTION_MODEL` and its price per minute.
- **Gemini**: a current vision model id supporting `response_json_schema` and `media_resolution`
  (`gemini_adapter.py`) and its price.

Put the ids and prices in `backend/.env.example` (commented examples) and `docs/setup.md` §2, with the
date checked and the source URL. Prices go in `APERTURE_ALLY_PRICES` as JSON:
`{"<model id>": {"input_per_mtok": 5.0, "output_per_mtok": 25.0, "verified_on": "YYYY-MM-DD", "source_url": "…"}}`.
If an adapter's request shape no longer matches the docs, fix the adapter and its test in
`backend/tests/test_providers.py`.

Then, **with the owner's OK**: `uv run pytest -m live -s tests/test_live.py` for each configured provider
(3 calls each on fixture images). Record latency, tokens, cost, and whether the output validated first
time or needed a repair.

## 2. macOS audio, keys and permissions

- Speech: `say -v '?' | head`; start the app with `APERTURE_ALLY_SPEECH_PROVIDER=say` and confirm the
  coach speaks, `S` stops it quickly, `R` repeats. Received/failure cues via `afplay` (Pop/Basso) play and
  mix with speech.
- Microphone: `APERTURE_ALLY_RECORDER=sounddevice` — macOS permission prompt appears for the terminal;
  a hold-to-talk clip records with sensible RMS; empty clips are skipped.
- Global keys: `APERTURE_ALLY_GLOBAL_KEYS=pynput`. Grant Input Monitoring (and Accessibility if asked)
  to the terminal; Diagnostics → Remote button test and "Learn key" see key-down/key-up with hold times.
- 8BitDo Micro + Karabiner (docs/setup.md §5): confirm the vendor/product ids (11720 / 36897) in
  Karabiner-EventViewer, that the rule maps buttons to F18 (talk) / F17 (pause) / F16 (cancel), and that
  hold-to-talk works with the remote in the other room of the house (Bluetooth range).
- `uv run aperture-ally preflight` end to end (interactive). Paste its GO/NO-GO summary.

## 3. Camera files (OM System E-M1 Mark II via OM Capture)

The OM System / OM Capture documentation was also blocked. Establish from the real software:

- How OM Capture writes into the watch folder: final names immediately or temp-then-rename? JPEG and
  ORF order and delay in RAW+JPEG? Any sidecar files? Does it ever rewrite a file after writing it?
  Watch with `fswatch -x <folder>` (brew) during 5 shots and paste the event log.
- `uv run aperture-ally inspect <a real .ORF and .JPG>` — ExifTool tags present (shutter, aperture, ISO,
  lens, exposure program, flash, orientation), embedded preview found, LibRaw decodes the ORF. Paste the
  scrubbed report (it removes serial/GPS/owner).
- Then the M1 30-press ingestion gate (docs/hardware-checks.md §1) with the owner at the camera.

## 4. The redesigned UI on the real screen

`./scripts/dev.sh` (or `aperture-ally serve` + built frontend), a mock session, then Diagnostics →
Replay `basic_loop`. Check in Safari and Chrome at the Air's default resolution:

- Every tab in Studio and Daylight (☀ button or `L`). Compare against `docs/design/*.dc.html` (open them
  in a browser locally). Save screenshots to `docs/screenshots/<theme>-<tab>.png`.
- Fonts work offline (turn Wi-Fi off, hard reload): IBM Plex must still render (it's bundled).
- Daylight outdoors in real sun at full brightness: can you read the verdict, the "DO THIS" line and the
  lost-detail overlay from arm's length? Note what fails.
- Keyboard map: Space talk, R/S, P pause, H lost detail, `[` rail, ←/→ filmstrip, ⌘1–6 tabs, ⌘↵ accept,
  Esc. None may fire while typing in a text field. Known risk: with a popover open during analysis, Esc
  may cancel the analysis instead of closing the popover — check and fix if so.
- Region drawing on the photo with a trackpad; brightness inspector zone hover paints the photo;
  "Show me on the photo" pins the glare; Compare with… picker; keeper confirm + Undo; revoke keeper in
  Coverage; New shoot form with Indoor/Outdoor.
- Window sizes: 1280×800 and a short window (< 820 px tall — the inspector should collapse).

## 5. Performance on the M4

- From Diagnostics → Timings after a replay, and `uv run aperture-ally export <session>`: evidence time per
  photo for real 20 MP JPEGs (target well under 1 s; it was ~0.45 s on the cloud container), framing score
  time (target < 30 ms), zone-mask generation time on first hover.
- Received → first audible speech with the mock provider (feel), and with a real provider (with OK).

## 6. Framing match on real fabric close-ups

The framing score (`backend/aperture_ally/imaging/framing.py`, `COMPARABLE` threshold) was calibrated on
synthetic images only. Using real photos (don't commit them): score pairs for (a) the same close-up
retaken with the light moved, (b) re-shot after a small nudge, (c) zoomed/reframed noticeably, (d) a
different garment. Write a tiny script that calls the module on the file pairs; record the table and
propose a threshold if (a)/(b) aren't comfortably above it and (c)/(d) below.

## 7. Report back

Finish `docs/local-verification-results.md`, update `POC_STATUS.md` rows that moved (e.g. "Hardware-verified"),
push, and summarise in chat: what passed, what failed and was fixed (commits), what's still blocked and
what the owner has to do by hand.
