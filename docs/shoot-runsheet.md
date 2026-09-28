# Run sheet: session 0 (setup) and shoot 1 (first real shoot)

Run with Claude Code as co-pilot in this repo. Claude runs the commands, watches the logs and tells you the
next step; you handle the camera, headphones and remote and report what you see and hear. Detailed
pass criteria live in [hardware-checks.md](hardware-checks.md); this sheet is the order of play.

**How we talk:** after each step, send a short note ("heard it", "no sound", "screen says …", "done").
Claude only acts when you message, so work between shots, not mid-shot. Remote control from your phone
works if you're away from the laptop.

## Before you start (decide once)

- [ ] **Budget for the day**, e.g. "up to $10 of API calls". Claude sets the session cap to match and won't
      ask again below it. Measured per photo (session 0): Sonnet 5.5 ≈ $0.025, Opus 5.5 ≈ $0.06,
      gpt-6-sol ≈ $0.018, gemini-3.8-flash ≈ $0.012; a voice question ≈ $0.005.
- [ ] **Provider for shoot 1**: Claude **Sonnet 5.5** (chosen in session 0: ~10 s per photo vs ~35 s for Opus 5.5).
- [ ] Kit:
  - E-M1 II charged, spare battery, USB-C cable; OM Capture set to PC + SD
  - **laptop charger** (the Air died mid-session 0)
  - AirPods Pro charged (they're the mic too, held open)
  - 8BitDo Micro charged, slider on **S** (hold L = talk, R = pause, B = cancel)
  - phone for 120/240 fps video (latency)
  - shoes/garments and lights set up

### Outdoors (if shoot 1 is outside)

- [ ] **Network at the spot:** run a speed test there. Each photo uploads ~0.5–1 MB to the model; a phone
      hotspot is the fallback. If the network drops, keep shooting: photos, measurements and keepers still
      work, and coaching can be retried later.
- [ ] **Power:** plug the Air in, or start near 100% and check it at each break. Keep the AirPods case and
      the Micro charged.
- [ ] **Screen:** switch to **Daylight** (☀ or `L`), brightness to full, laptop in shade or angled away from
      the sun. Note whether you can read the verdict and the "DO THIS" line at arm's length.
- [ ] **Light:** note sun or cloud and the time for each loop. Changing light between the baseline and the
      retake affects the comparison, and the coach can only guess at it.
- [ ] **Range:** check hold-to-talk works from the tripod: the Micro and AirPods to the laptop over Bluetooth.
- [ ] **Wind:** the AirPods mic handles it far better than the laptop's; if a transcript comes back wrong,
      turn out of the wind and ask again.

---

## Session 0: setup (~45 min, no photography pressure) — done 2026-09-28

Results and fixes: docs/local-verification-results.md ("Session 0 at the desk" onwards).

| # | You | Claude | Tell Claude |
|---|---|---|---|
| 0.1 | Paste API keys when asked (or add them to the keychain) | Writes `backend/.env` (models, prices, caps), runs `doctor` | — |
| 0.2 | — | Paid smoke test: 1–3 calls per provider (≈ $0.50) | — |
| 0.3 | Grant **Input Monitoring** + **Accessibility** to the terminal; restart it | Re-runs `doctor` | "granted" |
| 0.4 | Headphones on | Plays the received cue + a sentence; `S` stop, `R` repeat | what you heard, and where |
| 0.5 | Hold Space, say "What does f-number mean?" | Checks mic permission, RMS, transcript | whether the transcript was right |
| 0.6 | Pair the 8BitDo Micro; flip the slider when asked (D, then K) | Runs the controller probe (buttons, press/release, exclusive access); Claude writes it before session 0 | — |
| 0.7 | OM Capture: set the save folder, camera USB mode RAW/Control, RAW+JPEG | Starts `fswatch` on the folder | — |
| 0.8 | Take 5 shots (2 slow, 3 quick) | Reads the log: temp-then-rename? JPEG/ORF order and delay? rewrites? | "done" |
| 0.9 | Quit OM Capture | libgphoto2 probe (results doc, owner step 3b): detect, shots, trigger, aperture, live view, bracketing | what the camera screen did |
| 0.10 | — | `preflight` end to end, then records GO / NO-GO | — |

Afterwards Claude records every result in `docs/local-verification-results.md`. Code fixes are allowed in
session 0.

---

## Shoot 1: first real shoot (~2 h)

**Freeze rule.** Once step 1.3 starts, no code changes, and settings changes only if something blocks us.
Claude logs every change with a time. Fixes go in afterwards, so the day's numbers mean something.

| # | You | Claude watches | Pass (details in hardware-checks.md) |
|---|---|---|---|
| 1.1 | `./scripts/dev.sh`; Safari open on the Shoot tab; Diagnostics in a second window | App start, watch folder, provider health | GO |
| 1.2 | **30-press ingest gate**: 20 normal, a 5-shot burst, 3 shots with the app stopped, 2 after replugging USB | Every file arriving, pairing, recovered frames, no duplicate coaching | `ingest-report --expect 30` clean (§1) |
| 1.3 | **Three coaching loops**, one each for outsole, mesh close-up and hero: baseline → listen → change one thing (say "I moved …") → retake | Model latency, validation or repair, speech outcome, the experiment record | 3 complete experiments (§4.1) |
| 1.4 | **Rate each loop out loud**: "That helped" / "didn't help", and "Lesson: …" | The rating and lesson land on the card | on every card |
| 1.5 | **Bracket set**: one 5-frame AE bracket on the mesh | Only the base frame coached; frames 2–5 kept, silent | 1 assessment, 5 photos |
| 1.6 | **Stale advice**: shoot, then immediately switch shot; also 2 quick shots | Suppressed speech for the old shot; only the newest spoken | §4.2 |
| 1.7 | **PTT with OM Capture in front**, using the remote: ask one question, then hold 5 s | Press/release, hold time, auto-repeats ignored, answer spoken | §3 C, D, H |
| 1.8 | **Latency video**: film 10 ordinary captures (shutter, screen and an earcup in frame) | Stage timings for the same 10 | median / p95 (§5) |
| 1.9 | **Coverage**: accept keepers; leave one shot unresolved; Export | Keeper hashes, the unresolved shot listed | §4.3 |
| 1.10 | 5-minute debrief: what felt slow, confusing or wrong | Exports timings and telemetry, summarises | — |

**What Claude flags between shots:**
- a photo that didn't arrive or pair, or is stuck in `pending_retry`
- a model call over 10 s, a failure, or a repair
- advice spoken for the wrong photo, or not spoken
- spend against the budget
- anything that contradicts what you reported

## After the shoot

- Claude writes the day's results into `docs/local-verification-results.md` and the gates in
  `POC_STATUS.md` (Hardware-verified / Model-evaluated), with numbers.
- Claude builds a fix list, ranked by how much it hurt the shoot. Fixes land as commits after the shoot,
  not during it.
- Next: the owner dataset (30–50 photos) and the offline eval (`evals/README.md`), then the ~10-experiment
  teaching trial and the validation shoot (hardware-checks.md §6–7).
- Photos, recordings and session data stay on the Mac. Nothing personal gets committed.
