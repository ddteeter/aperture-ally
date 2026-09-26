# Hardware and live-trial checks (manual gates)

None of these have been run yet: they need the E-M1 Mark II, OM Capture, the M4 MacBook Air,
Bluetooth headphones, a microphone, optionally a Bluetooth remote, and API credentials. Simulator and
unit tests **do not** substitute for them. Record every result (pass *or* fail, with numbers) in
[POC_STATUS.md](../POC_STATUS.md) and [poc-report.md](poc-report.md).

Before each block: `cd backend && uv run aperture-ally doctor` shows no ✘, and the app runs with
`./scripts/dev.sh`. Keep `Diagnostics` open in a second browser window.

Suggested kit for timing: a phone that records 120/240 fps video, placed so one frame shows the camera
(shutter button/finger), the laptop screen (the *Received ✓* indicator / coach text), and can hear the
headphones (hold one earcup to the phone mic) — or use a wired earbud next to the phone mic.

---

## 1. M1 — tethered ingestion (30 presses)

Setup: `.env` with `APERTURE_ALLY_ASSESS_PROVIDER=mock` (no spend needed), OM Capture configured per
setup.md §3, camera in **RAW+JPEG**.

1. Sessions tab → create "HW ingest test", watch folder = OM Capture's save folder. Choose any shot.
2. Take **20 photos** at a normal pace (≥2 s apart). Include ≥5 RAW+JPEG (camera default).
3. Take **5 photos in a quick burst** (sequential mode, ~1 s apart).
4. **Restart check:** stop the backend (Ctrl-C). Take **3 photos** while it is stopped. Start it again.
5. **Reconnect check:** unplug the USB cable for ~10 s, reconnect, let OM Capture re-attach (restart
   OM Capture if needed), take **2 photos**.
6. Run: `uv run aperture-ally ingest-report --expect 30`.

Pass criteria:
- `logical_captures == 30`, `match: true`, `seq_gaps: []`.
- `raw_jpeg_pairs` ≈ number of RAW+JPEG frames (all of them if the camera was in RAW+JPEG), `raw_only: 0`.
- `captures_with_multiple_auto_assessments: []` and `captures_spoken_more_than_once: []` (no duplicate
  coaching, including for late RAW arrivals).
- The 3 photos from step 4 show `recovered` (3) and were **not** spoken aloud.
- `source_files_by_status` contains no `pending_retry`/`failed` left over (or each is explained).
- In the UI the images are upright (orientation) and a region drawn on the overview matches its crop.
- Spot-check 3 originals: the OM Capture files are unchanged (Finder dates), and copies exist under
  `~/ApertureAlly/sessions/<id>/originals/`.

Record: counts, any anomalies, OM Capture version, macOS version, whether "save to PC and card" was used.
Also note whether ExifTool reported ORF metadata (capture detail → EXIF shows lens, f-number, etc.).

## 2. M2 — real-provider coaching (three intentional examples)

Setup: provider keys + model IDs (setup.md §2), `uv run pytest -m live -s tests/test_live.py` passes.
Create a session with provider = OpenAI (repeat later with Gemini). Fill in the setup honestly
(tripod? continuous light? movable? manual exposure? auto ISO?).

Take and record three deliberate cases on real shoes:
1. **No essential change needed** — a well-lit, sharp outsole shot with the region drawn on the tread.
2. **Needs retake** — the mesh close-up with a hard light causing a visible hotspot on the mesh.
3. **Uncertain** — something the model can't decide from pixels (e.g. a criterion about colour accuracy
   under mixed light, or a very small region).
Then **missing metadata**: import a JPEG exported without EXIF (Preview → Export strips it, or
`exiftool -all= copy.jpg`) and check the advice does not state settings.

Pass: each gets a validated structured result; verdicts match intent (or disagreement is noted);
observations cite only supplied regions; no invented lights/gear/settings; the no-EXIF case has no
`camera settings` warning and no fabricated numbers. Record resolved model ids, tokens, latency, cost.

## 3. M3 — speech, microphone, PTT, remote

Setup: `APERTURE_ALLY_SPEECH_PROVIDER=say`, `APERTURE_ALLY_RECORDER=sounddevice`,
`APERTURE_ALLY_TRANSCRIBER=openai` (+ model), `APERTURE_ALLY_GLOBAL_KEYS=pynput`, key chosen via
Diagnostics → *Learn key*. Permissions granted (setup.md §5).

A. **Audible through Bluetooth headphones:** Shoot tab → *Repeat last advice* (or trigger any
   assessment). Pass: speech is heard in the headphones, not the laptop speakers. Note the voice/rate.
B. **Mic choice:** hold PTT and say "What does f-number mean?"; check the transcript on screen. Repeat with
   (i) headset mic, (ii) Mac mic. Note transcript accuracy and whether headphone audio quality dropped
   (Bluetooth call profile). Pick one and record it.
C. **Global PTT with OM Capture in front:** click into OM Capture so the browser is not focused. Hold the
   PTT key, ask a question, release. Pass: Diagnostics shows `press` then `release` with a plausible
   `hold_ms`; the answer is spoken.
D. **Key repeat:** hold the key for 5 s. Pass: Diagnostics shows `repeat` events but only **one**
   recording/voice turn.
E. **Interruption:** during a long spoken answer, press PTT. Pass: speech stops promptly. Measure with
   video: frames from key press to silence; target ≈ ≤300 ms. Also note Diagnostics
   `speech_stop_latency_ms` (process-level; Bluetooth adds output latency on top).
F. **Lost release:** set `APERTURE_ALLY_PTT_MAX_SECONDS=8`, restart; press and hold, then (simulate a lost
   key-up) switch focus/unpair the remote while holding, or just keep holding. Pass: after 8 s the state
   returns to idle, the turn is `timed_out`, nothing is transcribed. Restore 60 s.
G. **Toggle fallback:** `APERTURE_ALLY_PTT_MODE=toggle` (for pulse-only remotes): tap to start, tap to stop.
H. **Remote:** repeat C–E with the actual remote (e.g. AirTurn DIGIT 500 / 8BitDo Micro in keyboard
   mode). Record the key name, whether it produces held states or pulses, battery/sleep behaviour, and
   whether OM Capture also reacts to that key. **Do not claim remote compatibility without this.**

## 4. M4 — retake loop, stale suppression, coverage

1. **Three complete loops** (real provider): for three different shot types, take a baseline, listen to
   the advice, type/say what you changed (*What I changed* box), retake, and read the comparison.
   Fill in the experiment card (actual change, rating, criterion improved?, other worsened?, lesson in
   your words). Pass: three experiments with baseline → advice → retake → comparison recorded.
2. **Stale advice:** make a slow model call likely (large region, or simply act fast): take a photo and
   **immediately** switch the active shot. Pass: no advice for the old shot is spoken; the assessment
   shows `speech: suppressed`. Also: take two photos quickly — only the newest is spoken.
3. **Coverage:** accept keepers for every shot you completed; leave one shot with only a failed/uncertain
   candidate. Coverage tab → *Export*. Pass: every accepted shot resolves to a saved file (hash
   verified); the unaccepted one is listed as unresolved; contact sheet shows keepers + MISSING tiles.

## 5. Latency measurement

The app logs: file detected → file ready → evidence ready → model request/response → validated →
speech requested → speech process started → completed (`Diagnostics` timing table, `aperture-ally export`).
It **cannot** see the shutter press or audible onset. For ≥10 ordinary JPEG captures:
- **Shutter → file ready:** video frame of the shutter press to the frame where *Received ✓ photo #N* appears.
- **File ready → first audible speech:** from *Received ✓* to the first audible word in the video.
Report median/p95 with n, file sizes, network (Wi-Fi, speed test), provider/model, prompt version,
concurrency. Include failures/timeouts. Targets (hypotheses): local feedback p95 < 1 s from file-ready;
first useful speech median < 5 s, p95 < 10 s from file-ready; PTT silence ≈ ≤300 ms.

## 6. Live teaching trial (~10 experiments)

Across ≥3 shot types, run ~10 advice → retake experiments with a real provider. For each, in the
experiment card record: actual change, whether the relevant criterion improved (your judgement,
looking at the before/after), whether other criteria worsened, a helpful/neutral/harmful rating, and the
lesson in your own words **without looking at the advice text**. Then:

```bash
uv run aperture-ally eval trial --session <id-prefix>
```

Targets (hypotheses): ≥7/10 helpful, ≤1/10 clearly harmful, a useful explanation recalled after most
trials. Ten trials inform the next iteration; they do not establish reliability. If a knowledgeable
photographer can review a subset of before/after pairs, record where they disagree with you.

## 7. End-to-end validation shoot

The POC is **validated** only after one real tethered shoot of the six-shot running-shoe list with
spoken coaching, PTT follow-ups, retake comparisons and a completed coverage review (all shots accepted
or explicitly left unresolved). Export and attach `coverage.md`, `timing.md` and `teaching_trial.md`.
