# Local verification results (M4 MacBook Air)

Run on 2026-09-27 against `docs/local-verification.md`. Machine: MacBook Air M4, macOS 26.3 (25D125),
arm64, built-in display 2560×1664 (default "looks like" 1470×956). Branch `claude/hopeful-goldberg-uele3r`.

"PASS" means the plumbing works on this Mac. It says nothing about photographic reliability. Items that
need the owner at the camera, headphones or remote, or a paid API call, are **BLOCKED (owner)** and have
exact steps in [Owner steps](#owner-steps).

## Summary

| § | Item | Result |
|---|---|---|
| 0.1 | Tool versions | PASS |
| 0.2 | `check.sh` (pytest, ruff, typecheck, Vitest, build) | **FAIL → fixed** (`b87d704`), now PASS |
| 0.2 | e2e with Playwright's own Chromium | PASS |
| 0.3 | `doctor` + coloured output | PASS (Input Monitoring FAIL is expected until granted, §2) |
| 0.4 | platform / OpenCV / LibRaw versions | PASS |
| 1 | Anthropic ids, prices, request shape | PASS; default changed to `claude-opus-5-5` at the owner's request (`491b2c1`) |
| 1 | OpenAI ids, prices, request shape | **FAIL → fixed** (`2248317`): output budget too small for reasoning |
| 1 | Gemini ids, prices, request shape | **FAIL → fixed** (`1b159b5`): same budget issue, and thinking tokens missing from cost |
| 1 | Ids/prices recorded in `.env.example` + setup.md | PASS (`f6d38dd`) |
| 1 | Live smoke test (`-m live`) | BLOCKED (owner): no API keys on this Mac, and paid calls need an OK |
| 2 | `say` voices, cue sounds present | PASS (files and binaries only) |
| 2 | Speech audible, S/R, cues mix, mic, global keys, 8BitDo/Karabiner, `preflight` | BLOCKED (owner) |
| 3 | OM Capture file behaviour (fswatch) | BLOCKED (owner): prepared; one setting found (dated subfolders) |
| 3 | `inspect` on a real E-M1 II ORF + JPEG | PASS (and a privacy fix, `8eca25a`) |
| 3 | M1 30-press ingestion gate | BLOCKED (owner) |
| 3b | Direct USB control without OM Capture (libgphoto2 probe) | BLOCKED (owner): prepared, owner step 3b |
| 4 | Every tab, Studio + Daylight, Chrome + WebKit, screenshots | PASS, with a layout bug fixed (`ed0a966`) |
| 4 | Fonts offline | PASS (bundled, no external URLs); a Wi-Fi-off reload by hand is still to do |
| 4 | Keyboard map (all keys, never while typing) | **FAIL → fixed** (`6cc2461`): Space PTT dead after a mouse click in Chrome |
| 4 | Esc during analysis with a popover open (known risk) | **FAIL → fixed** (`ff81d0a`), plus the same bug in the Compare-with picker (`66fb155`) |
| 4 | Region drawing, zone hover, Compare with…, keeper confirm/Undo, New shoot | PASS (automated, Chrome) |
| 4 | 1280×800 and short window (< 820 px) | PASS: the inspector collapses |
| 4 | Real Safari (not WebKit) look, and Daylight in real sun | BLOCKED (owner) |
| 5 | Evidence, framing and zone-mask timings on real 20 MP JPEGs | PASS: all well under target |
| 5 | Received → audible speech (real `say`, real provider) | BLOCKED (owner) |
| 6 | Framing match on real fabric close-ups | BLOCKED (owner): script ready (`scripts/framing_pairs.py`) |

Fix commits, in order: `b87d704`, `ff81d0a`, `2248317`, `491b2c1`, `1b159b5`, `f6d38dd`, `ed0a966`, `6cc2461`,
`66fb155`, `4f03c7a` (screenshots), `8eca25a`.

---

## §0 Baseline

**0.1** `uv 0.11.7 (Homebrew, aarch64-apple-darwin)`, `node v25.9.0`, ExifTool 13.55 (brew),
`fswatch 1.22.0` installed for §3.

**0.2 `./scripts/check.sh`.** The first run failed, and only on macOS:
`tests/test_preshoot.py::test_apparel_template_and_raw_exif` gave `AssertionError: assert (None == 'E-M1MarkII')`.
The cloud build had no ExifTool, so `exif_raw` used Pillow's plain tag names. Here ExifTool (`-G0:1`) keys tags by
group, e.g. `EXIF:IFD0:Model`. The app code was correct; normalized metadata read `camera_model` fine. The test
now accepts both forms (`b87d704`).

The failure also stopped `check.sh` before `npm ci`, so the first frontend build failed on a stale
`node_modules` (`@fontsource/ibm-plex-sans` missing). That was an environment issue, not a bug.

Final run of the whole script: backend **151 passed, 3 live deselected**, ruff clean. Frontend typecheck clean,
Vitest **137 passed** (was 132; 5 tests added), build OK, e2e **2 passed** with Playwright 1.63's own
Chromium (`coach-loop` 37 s, `voice` 2 s).

**0.3 `aperture-ally doctor`** (no `.env`): `arm64 native: python 3.12.12 on arm64 ✔`, `exiftool: 13.55 ✔`,
`speech: say ... say=found ✔`, input devices `MacBook Air Microphone` (default) and `BigLongRun Microphone`.
- WARN: OpenAI/Gemini/Claude keys missing, and global keys `mode=none`. Both expected.
- FAIL: `Input Monitoring permission`. Expected until granted in §2.
- Colour: a TTY (via `script -q`) gets 32 lines with ANSI codes, bold green `✔ OK`, yellow `! WARN`,
  red `✘ FAIL`. Piped to a file there are 0 escape codes. `NO_COLOR=1` on a TTY gives 0. `FORCE_COLOR=1` piped
  gives 32.
- Whether the colours *look* readable in your Terminal theme is a 5-second eyeball check (owner step 0).

**0.4** `arm64 5.0.0 (0, 22, 1)`: OpenCV 5.0.0, LibRaw 0.22.1 (rawpy 0.27.1).

## §1 Model ids, prices and API shapes

Checked on 2026-09-27 against the live official docs: platform.claude.com, developers.openai.com and
ai.google.dev. The table with source URLs is in [setup.md → Models](setup.md#models). A ready-to-uncomment
`APERTURE_ALLY_PRICES` block is in `backend/.env.example`; I verified that it parses as multi-line JSON.

| Provider | Default / suggested | Cheaper | Notes |
|---|---|---|---|
| Claude | `claude-opus-5-5` $4/$20 | `claude-sonnet-5` $2/$10 | `claude-opus-5` ($5/$25) is still active; Anthropic's docs now recommend Opus 5.5 |
| OpenAI | `gpt-6-sol` $2/$10 | `gpt-6-luna` $0.10/$0.50 | openai.com/api/pricing returned 403; prices from developers.openai.com |
| OpenAI STT | `gpt-transcribe` $0.0045/min | `gpt-4o-mini-transcribe` ≈$0.003/min | |
| Gemini | `gemini-3.8-flash` $0.75/$3.75 (→ $1.50/$7.50 on 2027-01-01) | `gemini-3.5-flash-lite` $0.30/$2.50 | Google now calls `generateContent` "legacy" but "fully supported" |

**Claude: PASS.** Every part of the adapter's request shape matches the docs and the installed `anthropic` 1.8.0 SDK:
- `beta.messages.create` with `fallbacks="default"` and beta `server-side-fallback-2026-07-01` (still beta; the
  header date must be exactly that).
- `thinking={"type":"adaptive"}`.
- `output_config.format` json_schema and `output_config.effort` (`low|medium|high|xhigh|max`), both GA.
- `resp.model` is the serving model; the fallback is detected via the `fallback` content block or
  `usage.iterations`.

The default changed from `claude-opus-5` to `claude-opus-5-5` on the owner's call (`491b2c1`): it is cheaper and
Anthropic's recommended starting model. It is **not yet evaluated on your photos**. Opus 5.5's API-default effort
is `medium` (Opus 5's was `high`).

Known limitation, documented rather than fixed: when a request is declined and answered by the fallback model,
only the serving attempt's tokens are counted. Haiku 4.5 would need adapter changes, because it has no adaptive
thinking.

**OpenAI: FAIL → fixed (`2248317`).** The request shape matched: `input_text`/`input_image`, data URL, `detail`
(`low|high|auto|original`), `text.format` strict json_schema, `store=False`. The problem was the budget. Current
models reason at `medium` by default and spend `max_output_tokens` on reasoning first. The adapter sent 2000, and
OpenAI documents that this can return `status: incomplete` "before any visible output tokens are produced".
Changes:
- The budget is now 25 000, OpenAI's recommended reserve.
- New optional `APERTURE_ALLY_OPENAI_EFFORT` (`reasoning.effort`); the test covers both paths.

Advice recorded in setup.md: keep `detail=high`. On gpt-5.6-class models `auto`/`original` send full resolution,
about 28k tokens per 24 MP frame.

**Gemini: FAIL → fixed (`1b159b5`).**
- Same budget problem: thinking counts against `max_output_tokens` (2000 → 16 000).
- Cost bug: `output_tokens` recorded candidates only, but Gemini bills thinking as output. Cost estimates and the
  USD cap were therefore low. It now records candidates + thoughts, like OpenAI and Claude already do.
- Added optional `APERTURE_ALLY_GEMINI_THINKING_LEVEL`, `ultra_high` media resolution, and `finish_reason` in the
  empty-response error.

**Live smoke test: BLOCKED (owner).** There are no keys in the env, no `backend/.env` and none in the keychain.
Each paid call also needs your OK. See owner step 1.

## §2 macOS audio, keys and permissions

- `say -v '?'`: 184 voices, including Samantha (en_US), Daniel (en_GB) and Karen (en_AU).
- `/System/Library/Sounds/Pop.aiff` and `Basso.aiff` are present; `afplay` is found.
- **Not run:** anything that makes sound, records the mic or listens to keys. Hearing it is the test, and the
  mic/Input Monitoring prompts need you.
- Neither Karabiner-Elements nor 8BitDo Ultimate Software is installed. Owner step 2.

## §3 Camera files

**OM Capture: 3.2.0.1** (`com.om-digitalsolutions.OMCapture`) is installed. From its preferences:
`OlyUDAutoImportCreateDateDirectory = 1` and `OlyUDSaveMediaSelectWhenLaunched = 1`. The first may put photos in
a **dated subfolder** of the save folder, and the second means it asks where to save at launch. The watcher is
recursive by default (`watch_recursive=True`), so a dated subfolder is still ingested. The fswatch run will
confirm this. No recent save path is stored yet.

**`inspect` on real E-M1 Mark II files: PASS.** Files: `_5220013.ORF` + `_5220013.JPG` from
`~/Pictures/Lightroom Saved Photos`, read in place, not copied or committed.

| | ORF (17.7 MB) | JPEG (4.1 MB) |
|---|---|---|
| Metadata | ExifTool, 231 tags, 113 ms | ExifTool, 226 tags, 108 ms |
| Normalized | E-M1MarkII · LEICA DG SUMMILUX 25/F1.4 · 1/1250 s · f/1.4 · ISO 200 · 25 mm · no flash · aperture priority · orientation 1 | identical |
| Camera tags | Olympus maker notes: FocusMode, AFPointSelected, ImageStabilization, DriveMode, Flash*, PreviewImage* | same |
| RAW | LibRaw decodes 5240×3912 RGBG; embedded JPEG preview (1.0 MB) used, 39 ms; evidence at 3200×2400 in 166 ms | n/a |
| Decode / evidence | n/a | 5184×3888 decode 81 ms; evidence 332 ms |

- Scrubbing: the JSON has no serial, GPS or path strings (grep count 0).
- **Privacy fix (`8eca25a`):** `--all-tags` also included ExifTool's `SourceFile` and `File:System:Directory`,
  which carry the macOS user name and folder names. They are scrubbed now.
- Worth knowing: a RAW-only capture is coached from the **3200×2400 embedded preview**, not the full 20 MP.

**File behaviour, and the M1 30-press gate: BLOCKED (owner).** Owner step 3.

## §4 The redesigned UI

Setup: `aperture-ally serve` with mock adapters and a throwaway data dir, then `replay basic_loop` (7 photos,
3 loops, keeper, late RAW). The browsers were Playwright Chromium and WebKit 26.6 at 1470×866, the Air's viewport
below the menu bar. Screenshots are in `docs/screenshots/` (Chrome):
- `{studio,daylight}-{shoot,coverage,shotlist,setup,sessions,diagnostics}.png`
- `{studio,daylight}-shoot-1280x760.png`

No console errors or page errors in either engine or theme.

- **Layout bug (fixed `ed0a966`).** Diagnostics → Health: a long watch-folder path didn't wrap and crushed the
  label to one word per line ("Watch / folder: / last / file / 57 / s / ago"). The label now keeps its line.
- **Fonts: PASS.** Both engines loaded IBM Plex Sans 400/500/600/700 and Plex Mono 400/500/600 from the local
  server (7 woff2 files in `dist/assets`). The built CSS/JS has no external URLs, so nothing needs the network.
  A literal Wi-Fi-off hard reload is still worth 30 seconds (owner step 4).
- **Keyboard map, Chrome and WebKit** (automated, observed through requests and DOM state):

  | Key | Result |
  |---|---|
  | ⌘1–6 | switch tabs |
  | ← → | step the filmstrip |
  | H | lost-detail toggle |
  | `[` | rail collapse |
  | P | pause/resume (PATCH session) |
  | R | `/coach/repeat` |
  | S | `/coach/stop` |
  | Space hold | `/voice/start` → `/voice/stop` |
  | Esc | `/voice/cancel` |
  | Typing `[hplrs x`, ← and ⌘2 in "What I changed" | nothing fired: text typed, tab, theme, rail and film all unchanged, no requests |

- **Space PTT after a mouse click in Chrome: FAIL → fixed (`6cc2461`).** Chrome focuses a button on click
  (Safari doesn't), and focused controls kept Space for themselves. After clicking a thumbnail, a tab or a shot,
  holding Space did nothing. Controls now keep Space only when focused by keyboard. The focus origin is tracked
  from pointerdown → focusin, because Chrome turns on `:focus-visible` during the keydown itself. Re-verified in
  both engines. Clicked controls are not re-activated, and a Tab-focused Repeat button still gets Space.
- **Esc-during-analysis risk: confirmed and fixed (`ff81d0a`).** The analysis view's Esc → cancel listener
  registered on `window` before a popover opened, so Esc cancelled the analysis *and* closed the popover.
  Deselecting a region mid-analysis had the same problem. Popovers and the region editor now claim Esc in the
  capture phase. Vitest reproduces both cases (`EscPriority.test.tsx`).
- **Compare-with picker (fixed `66fb155`).** In the browser, Esc did not close it: Esc went to `/voice/cancel`,
  and a click outside left it open. It now uses the shared dismiss hook, with a test.
- **Interactions, automated in Chrome.** All worked:
  - Zone hover requests `zone_highlights` and paints the mask on the photo.
  - Compare with… lists candidates with framing %.
  - Region editor: select, and Rename/Delete (drawing by drag is covered by Vitest and e2e).
  - Keeper confirm dialog and Undo (e2e).
  - New shoot has Indoor/Outdoor.
- **Window sizes.** At 1280×800 everything fits. At 1280×760 the brightness inspector collapses to its one-line
  summary as designed (`*-shoot-1280x760.png`).
- **BLOCKED (owner).** Real Safari (WebKit is only a proxy); Daylight in real sun at arm's length; region
  drawing on the trackpad by hand. Owner step 4.

## §5 Performance on the M4

Measured with `build_evidence` / `framing` / `ensure_zone_mask`, the same functions the app calls, on
**12 real E-M1 II JPEGs** (5184×3888, 3.7–4.4 MB, 2 passes, n=24):

| Stage | M4 | Target | Cloud container |
|---|---|---|---|
| Evidence per photo | median **310 ms**, max 396 ms | well under 1 s | ~450 ms |
| Stages (typical) | decode+orient+colour 79, overview 33, framing signature 12, crops+region stats 99, global stats 75 ms | | |
| Framing score, uncached pair | **0.3–2.8 ms** (signature from disk 1.3 ms; compute 12.8 ms) | < 30 ms | |
| Zone masks, first hover (all five written) | **345–400 ms**; next zone 0.04 ms | | |
| RAW-only preview (ORF) | 39 ms embedded preview, evidence 166 ms | | |

- Synthetic 9 MB JPEGs gave a 244 ms median.
- Mock replay in the app (Diagnostics → Timings, n=7): capture → received median 0.8 s (p95 1.6 s, which includes
  the stability wait), local measurements 0.1 s, received → speech process started 0.2 s.
- Received → first **audible** speech with real `say` and a real provider: BLOCKED (owner step 5).

## §6 Framing match on real fabric close-ups

BLOCKED (owner): it needs purpose-shot pairs. `scripts/framing_pairs.py` is ready. It runs pairs through the
app's own evidence + framing path and prints the table plus a threshold suggestion. On synthetic fixtures:
(a) 0.991 texture, (d) 0.277 layout, current threshold 0.65. Owner step 6.

---

## Owner steps

Everything is prepared; each step says exactly what to run. From the repo root unless noted.

**0. Doctor colours (10 s).** Run `cd backend && uv run aperture-ally doctor` in your usual terminal. Are green OK,
yellow WARN and red FAIL readable on your theme?

**1. Keys + paid smoke test (needs your OK; ≈ $0.50, cap $1).**
1. `cp backend/.env.example backend/.env`, add the keys (or use the keychain recipe in setup.md §2).
2. In `.env`, set `APERTURE_ALLY_OPENAI_MODEL=gpt-6-sol`, `APERTURE_ALLY_GEMINI_MODEL=gemini-3.8-flash` and
   `APERTURE_ALLY_TRANSCRIPTION_MODEL=gpt-transcribe`, and uncomment `APERTURE_ALLY_PRICES`.
3. `cd backend && for i in 1 2 3; do uv run pytest -m live -s tests/test_live.py; done`. That is 3 calls per
   configured provider.

Rough cost per call (one overview + up to 3 crops, about 8–10k input tokens, 2–4k output with thinking):
Opus 5.5 ≈ $0.08–0.12, gpt-6-sol ≈ $0.04–0.06, gemini-3.8-flash ≈ $0.01–0.02. A repair doubles one call.

**2. Audio, mic, keys, remote (at the Mac with headphones).**
1. In `.env`: `APERTURE_ALLY_SPEECH_PROVIDER=say`, `APERTURE_ALLY_RECORDER=sounddevice`,
   `APERTURE_ALLY_GLOBAL_KEYS=pynput`.
2. System Settings → Privacy & Security → **Input Monitoring** (and Accessibility): enable your terminal, then
   restart it.
3. Run `./scripts/dev.sh`, create a mock session, Diagnostics → Replay `basic_loop`.
   - Listen: the coach speaks in the headphones; `S` stops it fast; `R` repeats; the Pop cue is audible over speech.
   - Hold Space: the mic permission prompt appears, and the transcript shows.
   - Diagnostics → Learn key: press F18 and see press/hold/release.
4. Remote: install Karabiner-Elements and add the rule from setup.md §5. In EventViewer, confirm vendor
   11720 / product 36897, and try hold-to-talk from the other room.
5. `cd backend && uv run aperture-ally preflight --no-paid` (drop `--no-paid` after step 1), then paste the
   GO/NO-GO summary.

**3. OM Capture (camera tethered).**
1. OM Capture → save folder `~/Pictures/OMCapture/ApertureAlly` (note whether it makes a dated subfolder).
2. In a terminal: `fswatch -x -t -r ~/Pictures/OMCapture/ApertureAlly | tee ~/fswatch-omcapture.log`.
3. Take 5 shots in RAW+JPEG (2 slow, 3 quick), then Ctrl-C and send me the log. It will show temp-then-rename vs
   final names, JPEG/ORF order and delay, sidecars, and rewrites.
4. Then the 30-press gate in hardware-checks.md §1.

**3b. Can we drop OM Capture? (≈ 20 min, free, at the camera).** Background: Olympus publishes no USB protocol
or desktop SDK. libgphoto2 (open source, reverse-engineered PTP + Olympus extensions) lists the E-M1 Mark II
with capture and live view, and has OM-D settings for aperture, shutter speed, ISO, exposure compensation,
focus mode and image quality. Known open report: "PTP General Error" on `--capture-image` (E-M1 II,
libgphoto2 2.5.23, marked pending-fixed). This probe decides whether the app could talk to the camera itself:
for ingestion, for self-shots (live view on the laptop, remote trigger), and for changing aperture.

1. `brew install gphoto2`. **Quit OM Capture.** Camera: USB mode **RAW/Control**, RAW+JPEG, plugged in.
2. `gphoto2 --auto-detect && gphoto2 --summary | head -40`. If it says the device is busy/claimed, macOS's
   own camera service has it: `killall -9 ptpcamerad` and retry. Note whether that was needed.
3. **Camera-initiated shots (replaces the watch folder):**
   `mkdir -p ~/gp-test && cd ~/gp-test && gphoto2 --wait-event-and-download=60s`, then press the shutter 3 times
   (1 slow, 2 quick). Do both the JPEG and the ORF arrive? How long after each press? Do the camera's buttons
   and dials still work in this mode?
4. **Remote trigger (the 8BitDo button would call this):** `time gphoto2 --capture-image-and-download` × 3. Note
   the time and any "PTP General Error".
5. **Settings:** `gphoto2 --list-config > ~/gp-config.txt`, then `gphoto2 --get-config aperture`, then
   `gphoto2 --set-config aperture=<one of the listed choices>` and check the camera's screen changed. Repeat
   for `shutterspeed`, `iso`, `exposurecompensation`. (Aperture only changes in A or M mode.)
   Bracketing: `gphoto2 --get-config drivemode` (no bracketing choice is known to libgphoto2), and search
   `~/gp-config.txt` for `d110`/`d111` (Olympus AE-bracketing frames/step; defined in libgphoto2 but not
   named). Then set AE bracketing on the camera (e.g. 5 frames, 1 EV), repeat step 3 and note whether all
   frames arrive and in what order.
6. **Live view:** `gphoto2 --capture-preview` (one frame, saves a JPEG: note size/time), then
   `gphoto2 --capture-movie=10s --stdout > lv.mjpg` and note the frame rate (`ls -l`, or open in VLC).
7. Send me the terminal output, `~/gp-config.txt` (remove serials if shown) and your notes; delete `~/gp-test`.
   Don't send the photos.

**4. Safari, offline, sun.**
- Open `http://127.0.0.1:8765` in Safari. Check each tab in both themes (`L`), then compare with
  `docs/screenshots/`.
- Turn Wi-Fi off and press ⌘⇧R: Plex should still render.
- Outdoors at full brightness, in Daylight: can you read the verdict, the "DO THIS" line and the lost-detail
  overlay (`H`) from arm's length?
- Draw a region with the trackpad.

**5. Audible latency.** After steps 1–2, film 10 captures at 120/240 fps per hardware-checks.md §5.

**6. Framing pairs (don't commit the photos).** Shoot four pairs of one fabric close-up:
- (a) same framing, light moved
- (b) nudged slightly
- (c) zoomed or reframed noticeably
- (d) a different garment

Write `pairs.csv` lines like `a,light moved,~/Pictures/x/P1.JPG,~/Pictures/x/P2.JPG`, then run
`cd backend && uv run python ../scripts/framing_pairs.py ~/pairs.csv` and paste the table. Two or three pairs per
case give a better threshold.

---

## Session 0 at the desk (2026-09-28)

**Camera over USB: PASS.** The E-M1 II offers six USB modes when connected (Storage, MTP, PC RAW,
camera→screen icon, Print, PCM Recorder). **The camera→screen icon is tethering**; "PC RAW" is RAW editing
with the camera's engine. The Mac then sees `OLYMPUS E-M1MarkII`, USB id `0x07B4:0x0130`, at **USB 2.0
(480 Mb/s)**. That's the id libgphoto2 lists with capture + live view. OM Capture 3.2.0.1 was set to save
to PC + SD.

**OM Capture file behaviour (fswatch + a 20 ms size poll): PASS, best case for us.**

| | Observed |
|---|---|
| Folder | `~/Pictures/OM Capture/<YYYY_MM_DD>/` (dated subfolder; the app's watcher is recursive) |
| How files appear | **renamed in, already at final size**; never grew, never rewritten, no sidecars |
| RAW+JPEG order | **JPEG first**, ORF **0.94–1.39 s later** (median ≈ 1.06 s; the ~21.6 MB ORF over USB 2.0 ≈ 21 MB/s) |
| Sizes | LF JPEG ≈ 8.6 MB, ORF ≈ 21.6 MB |
| Quick shots | the next JPEG queues behind the previous ORF (≈ 1.4 s apart) |
| Shutter → JPEG on the Mac | ≈ 1–2 s (JPEG capture time has 1 s resolution only; phone video in shoot 1 will measure it) |
| Brackets (AE, 7 frames here) | every frame transferred; RAW-only when the camera is set to RAW |

On macOS a rename into the folder reaches watchdog as "file created" ~10 ms later (tested), so the app sees
each file at once.

Fix from this (`9dc27d7`): a JPEG that fully decodes on first sight is ready immediately (≈ 750 ms saved
before the model call). The faster ingest exposed two races, both fixed and tested:
- one file under two paths (`/var` vs `/private/var`) became two captures;
- later bracket frames made the base frame's advice look stale, so it was suppressed.

**8BitDo Micro: PASS in S mode.**
- **K mode:** a Bluetooth keyboard `0x2DC8:0x9021` (keyboard, consumer and system-control interfaces).
  Opening it is refused without Input Monitoring.
- **S mode:** a **Switch Pro Controller** `0x057E:0x2009` (gamepad). It **opens with no permission**.
  Report `0x3F` sends clean press/release events: A `0x02`, B `0x01`, L `0x10`, R `0x20` in byte 1; the
  D-pad is reported as the left stick (byte 7: up = `0x00`, centre = `0x80`). A 3.74 s hold of L arrived as
  exactly one press and one release, with no auto-repeat.
- **Conclusion:** use S mode, read directly by the app. No Karabiner, no remapping, no Input Monitoring,
  and nothing leaks into OM Capture.
- Still to check: sleep/wake and reconnect behaviour, range.
- The owner notes the iOS app can remap K mode to custom keys/combos; that's the fallback.

**Host note.** This session runs under `herdr` (launched by launchd, not a terminal window). Any macOS
permission prompts (microphone, Input Monitoring) will name that host.

### Direct USB control without OM Capture (owner step 3b): PARTIAL PASS, promising

gphoto2 2.5.32 / libgphoto2 2.5.34 (Homebrew), OM Capture quit, camera in the camera→screen USB mode. No need
to stop macOS's `ptpcamerad`. libgphoto2 recognised the Olympus OM-D extension (vendor id `0xfffd`).

| Check | Result |
|---|---|
| Detect / summary | PASS: `E-M1MarkII`, battery level readable (22%), 300+ properties |
| Read settings | PASS: aperture (f/1.0–f/91, was f/8.0), shutter speed, ISO (Auto), exposure comp, focus mode, image format (Large Fine JPEG+RAW), white balance, metering; bracketing props `0xd110` (frames, coded) and `0xd111` (step) exist, meaning not yet decoded |
| **Set aperture** | **PASS**: f/8.0 → f/5.6 from the Mac; the camera display updated (owner) and the next photo was f/5.6 |
| Set focus mode | PASS: Manual and back to Automatic |
| **Live view** | **PASS**: 1024×768 frames; **≈ 6 fps** streaming (~88 kB/frame); a single-frame command takes ~3.1 s, almost all of it reconnecting |
| **Remote trigger** | **PASS, slow in the CLI**: the shutter fired every time (owner heard each), the photo downloaded (JPEG + ORF, correct settings). `--capture-image-and-download` took 17–21 s; with `--trigger-capture`, the camera reports "captured" (event `c101`) **≈ 0.3 s** after the trigger, but the gphoto2 CLI only fetches new files when its wait ends (+9 s). Photos sent to the PC reuse a placeholder name (`_9280578`), so an app must name files itself |
| **Camera-button shots** | **FAIL as-is**: the owner pressed **twice**. The first press raised only `c105`, nothing downloaded; the second raised `c101`, and its JPEG downloaded at the end of the wait; **the ORF did not** |
| Connect time | ~2.8 s per CLI invocation (one-off for a persistent connection) |

**Assessment.** The camera side is capable: settings, live view, trigger and "photo taken" events all work over
USB without OM Capture. The CLI's event handling is the weak point: it ignores Olympus's `c101`, and it fetches
late and incompletely; camera-button presses were missed (1 of 2) and ORFs not fetched. `c105` needs decoding. An app would hold one connection (python-gphoto2 or libgphoto2 directly), and on `c101`
list and download the new objects right away. Estimated JPEG arrival ≈ 0.3 s + 0.4 s transfer; **unproven
until a small spike does it in code**. That spike, plus decoding the bracketing properties, is the next step
before any decision to drop OM Capture.

### Keys, smoke test, audio and mic (session 0, 2026-09-28)

**Live smoke test: PASS.** Every call validated first time, no repair; all said `needs_retake` on the synthetic
glare fixture. One call each (n=1, synthetic image: says nothing about quality):

| Model (effort) | Model call | ≈ $/photo |
|---|---|---|
| claude-sonnet-5-5 (low / default high) | 8.8 s / 10.3 s | $0.023 / $0.025 |
| claude-opus-5-5 (low / default medium) | 11.5 s / 35.1 s | $0.047 / $0.061 |
| gemini-3.8-flash (default) | 12.5 s (18–23 s in later preflights) | $0.012 |
| gpt-6-sol (default medium) | 19.2 s (13.5–14.7 s later) | $0.018 |

Shoot 1 runs on **Sonnet 5.5** (owner's call); Opus 5.5 at its default effort is too slow for at-camera coaching.
Every provider is far above the 5 s median target, so streaming the spoken advice is a priority after
session 0. Claude Sonnet 5.5 (released 2026-09-28, $2/$10) added to the docs. Fix `a7eaa60`: an empty setting
(e.g. `APERTURE_ALLY_CLAUDE_EFFORT=`) no longer fails start-up.

**Speech and cues: PASS after fixes.**
- Output: AirPods Pro over Bluetooth, heard in the headphones.
- The owner picked **270 wpm** (≈ 1.5×; 190 felt slow) and **Glass** as the received sound (Pop and Tink got
  lost under speech).
- Both are now **live settings in the Coaching popover** with "hear it" samples, saved per person (`a9ca6fe`).
- `say` lost the **last ~0.2 s of every utterance** on the AirPods ("cherry" → "cher"), even with no cue or mic
  involved. A 400 ms trailing silence fixed it in an A/B listen (`b5e29cb`).

**Microphone: PASS after fixes.**
- **Default input switch:** macOS switched the default input to the AirPods when they connected. Opening their
  mic flips them to call mode (24 kHz), which garbled a tone that was playing.
- **Why the AirPods mic anyway:** it's the practical one at the camera. A MacBook mic is estimated to be
  reliable only within ~1 m indoors, and less outdoors in wind (estimate, not measured).
- **Measured:** opening the AirPods mic takes **0.62 s** before audio flows. The owner couldn't hear a quality
  difference in call mode.
- **So the mic is held open** (`APERTURE_ALLY_MIC_ALWAYS_OPEN`, `87f6343`), with a **300 ms pre-roll**: the first
  word survived when the owner spoke as they pressed. Audio outside a turn stays in a 2 s memory ring.
- **Headphones leaving mid-shoot:** with the AirPods in the case, the stream died, and every reopen failed until
  restart (PortAudio reads the device list once).
  - Fixed: the device list is re-read before each open; the app falls back to the Mac mic ~1 s after the AirPods
    leave, and switches back within ~5 s of their return; liveness detection catches a stream that's "open"
    but silent (`c0cf723`, `d3c234f`).
  - Verified at the desk: AirPods → fallback (1 s) → AirPods; a question afterwards was transcribed and answered.
  - A press made just as the AirPods leave loses that turn (seen once).
- **Transcription and answers:** gpt-transcribe 1.3–2.1 s; typed/voice answers from Sonnet 5.5 about 4.2–4.4 s;
  release → speech ≈ 5.5–6.4 s.
- **Bug fixed** (`06a8af0`): an empty transcript fell back to the SDK object's repr and would have been sent to
  the coach as a question.

**preflight: GO** (warnings only: global keys off; headphones unconfirmed under `--yes`; Gemini slow). Fixes from
running it:
- no false Input Monitoring NO-GO with global keys off;
- the mic prompt is spoken, not only printed (the owner couldn't see it);
- the tone plays in full, and the mic window is 5 s;
- the Gemini SDK warning is off (`06a8af0`, `ca7222a`).

**Still open after session 0:**
- The app can't read the 8BitDo in S mode yet, so remote push-to-talk isn't wired up. Browser Space works.
- Sonnet 5.5 latency: 9–10 s per photo.
- Transcription is priced per minute, which the price table can't express; shown as "unpriced", never capped.

Spend in session 0 ≈ **$0.21**.
