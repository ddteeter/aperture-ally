# Spike: native audio latency (built-in speakers, measured with the built-in mic)

**Question.** Should Aperture Ally move real-time audio (per-press ticks, short spoken values) out of `say`/`afplay`
subprocesses and into a long-lived native process?

**Answer.** Yes, for spoken values especially. Here, `say` took about **960 ms** from request to audible onset. It
spends that time loading the voice in each new process. A pre-warmed in-process `AVSpeechSynthesizer` took **112 ms**,
and pre-rendered speech buffers took **76 ms**. For ticks, `afplay` took **168 ms**. A persistent in-process output
stream took **47–59 ms**, and the measurement loop's own floor is about 45 ms. The tick gain does not need Swift:
Python `sounddevice` with a persistent stream is as fast as `AVAudioEngine`.

Machine: MacBook Air M4, macOS 26 (Darwin 25.3), Swift 6.2.3. Run on 2026-09-28.

## Method

- **Path:** output to "MacBook Air Speakers" and recording from "MacBook Air Microphone". Both devices are chosen
  explicitly: `say -a`, `AVAudioEngine` output unit `CurrentDevice`, the sounddevice `device=`, and a HAL IOProc on
  the mic. `afplay`, plain `say` and `AVSpeechSynthesizer.speak` have no device option, so `DefaultOutputGuard`
  points the default output at the speakers and restores it on exit. The speakers were already the default because
  the AirPods were disconnected, so the guard changed nothing. The speaker volume was raised from 0.25 to 0.45 for
  the run and then restored to 0.25 (checked afterwards).
- **One clock:** everything uses `CLOCK_UPTIME_RAW` ns (= `mach_absolute_time`). The Python harness stamps each
  request just before it acts (spawns the process or writes the stdin line). The recorder is `audiolat record`, a
  HAL IOProc, and it logs the host time of every 512-frame input buffer. A linear fit maps clock to sample index
  (max fit residual < 0.13 sample). An `AVAudioEngine` input tap gave the same numbers, as a cross-check.
- **Onset:** a high-pass filter (x minus a centred 2 ms moving average) feeds a centred 1 ms RMS envelope. The
  threshold is 2.5 × the envelope maximum over the 1.6 s of ambient sound at the start of each recording (0.008–0.016
  full scale). The onset is the first sample above threshold after the request. A trial is discarded if sound was
  already present in the 100 ms before the request. Resolution is about ±1 ms. 12 trials per candidate, with 0–120 ms
  random jitter between them. Subprocess trials never overlap: each waits for the previous process to exit, then
  0.4 s.
- **Tick sound:** `tick.wav` is a 40 ms, 1.5 kHz burst with a 0.5 ms attack at −1 dBFS, played by every tick
  candidate. `Tink.aiff` was too quiet at modest volume: SNR ≈ 9 dB in the recording, with no reliable detection.
  `afplay` latency does not depend on which file it plays.
- **Speech:** "f 5.6" in the system default voice. `AVSpeechSynthesizer` renders 22.05 kHz mono float. The rendered
  lengths are 1313 ms active for AVSpeech and 1232 ms for `say -o`, so both probably use the same voice.

Code: `audiolat.swift` (Swift CLI: devices, default-output and volume get/set, HAL recorder, long-lived `player`,
`speak-once`, render info), `measure.py` (acoustic harness and analysis), `events.py` (silent software-event
timings). Recordings go to `$TMPDIR/aa_audiolat` and are deleted after each run. Raw numbers are in `results.json`
and `results_events.json`.

```sh
swiftc -O -o build/audiolat audiolat.swift
../../backend/.venv/bin/python measure.py --only ticks        # also: speech, tail, interrupt (~1–2 min of sound each)
../../backend/.venv/bin/python events.py                      # silent; requires output muted
```

## 1–4. Request → audible onset (ms, n = 12)

The **loop floor** is about 45 ms. The best path, a persistent 128-frame stream, measures 47 ms. CoreAudio reports
only about 13 ms for it (output latency 60 + safety offset 48 frames + a 128–512-frame buffer; input 14 + 36 frames).
The other ~30 ms is DSP/converter latency in the built-in speaker/mic hardware that CoreAudio does not report. This
setup can't split it between output and input. **Compare candidates by their differences.**

| Candidate | Median | p90 | Min–max | Minus best tick |
|---|---:|---:|---:|---:|
| **Ticks** | | | | |
| 2. `afplay tick.wav` subprocess (today's cue path) | **167.8** | 170.0 | 149.6–173.3 | +121 |
| 3b. Swift `AVAudioEngine` + `AVAudioPlayerNode`, pre-loaded buffer, default IO buffer (512 frames) | 59.0 | 65.5 | 55.1–65.6 | +12 |
| 3b′. Same, IO buffer set to 128 frames | **48.1** | 48.8 | 47.3–49.7 | +1 |
| 4. Python `sounddevice` persistent `OutputStream(latency="low")`, pre-loaded numpy buffer | **46.7** | 47.1 | 46.1–47.3 | 0 |
| **Spoken "f 5.6"** | | | | |
| 1a. `say` subprocess, text on stdin (exactly as `SaySpeech` does it), default output | **958.2** | 975.0 | 932.6–1450.1 (first call cold) | +911 |
| 1b. `say -a "MacBook Air Speakers"` | 968.5 | 984.8 | 423.1–1063.2 | +922 |
| 3a. `AVSpeechSynthesizer.speak`, long-lived process, pre-warmed | **112.3** | 118.1 | 105.0–118.6 | +66 |
| 3c. `AVSpeechSynthesizer.write` → player node on the speakers (render on demand) | 96.1 | 98.1 | 86.6–98.2 | +49 |
| 3d. Pre-rendered buffer (rendered at startup, leading silence trimmed) → player node | **76.2** | 79.6 | 68.5–80.3 | +30 |

Why `say` is so slow: running `say -o file "f 5.6"` without playing anything takes the same time (wall time
967/959/969 ms). The cost is process startup plus voice load, and synthesis itself is fast. The cost depends on the
voice (render wall time, silent, n=3 each): default **~965 ms**, Samantha ~535, Alex ~590, Daniel ~410,
Albert ~335. Even the cheapest voice costs a few hundred ms before audio can start, and every new utterance pays it
again.

Speech onsets rise more slowly than the tick, so 3d is about 17 ms later than 3b on the same engine. The threshold
crosses later on a soft onset.

## 5. Tail clipping (audible duration, onset → last sample above threshold; ms)

| Case | n | Median | Range | Verdict |
|---|---:|---:|---:|---|
| `say "f 5.6"` (no tail) | 8 | 1196.6 | 1194.2–1196.6 | not clipped on built-in speakers |
| `say "f 5.6 [[slnc 400]]"` | 8 | 1187.1 | 1187.0–1490.5 | same as above (no difference) |
| AVSpeech `speak`, long-lived process | 8 | 1282.0 | 1280.5–1777.1 | reference; 5/8 at 1280–1282 |
| AVSpeech `speak`, process **exits on `didFinish`** | 6 | 1052.4 | 4 clean trials: 1043–1061 | **clipped by ~0.22–0.24 s** |

- On the built-in speakers, `say` is not clipped: adding the 400 ms silence changes nothing. The AirPods clipping
  seen earlier comes from the Bluetooth route (the stream ramping or tearing down when the process exits), and this
  setup can't reproduce it.
- `AVSpeechSynthesizer.didFinish` fires about **0.23 s before the audio has finished playing**, even on the built-in
  path. A process that exits on `didFinish` loses the end of the utterance. This is the same mechanism as `say`, and
  it is stronger. A long-lived companion does not exit, so it doesn't clip. Don't treat `didFinish` as "audio done"
  when sequencing, for example before re-opening the mic. Add about 250 ms, or play pre-rendered buffers and use the
  player node's `.dataPlayedBack` completion.
- Anomalies: 3 long-lived trials measured ~1.75 s, 2 exit-on-finish trials ~2.1 s, and 2 had no onset. These were
  probably other sounds inside the window. The owner muted the output shortly afterwards, so the owner may also
  have been making noise. The clean trials are tightly clustered.

## 6. Interruption (a long sentence, then a new value 1.5 s in)

The acoustic run of this section didn't finish. **The system output was muted partway through it** (by the owner,
presumably; the harness only sets volume and default device, never mute). The harness did not unmute. These numbers
are **software event timings recorded silently with the output muted** (`events.py`, n = 8), combined with the
acoustic offsets above:

| Path | Old speech stops | New value starts (software) | Estimated audible new value |
|---|---|---|---|
| `say`: `terminate()` → wait → spawn new `say` (today) | process exits in **1.6 ms** median (p90 2.5) | new process needs ~960 ms (acoustic 1a) | **≈ 1 s** after the request |
| `AVSpeechSynthesizer.stopSpeaking(.immediate)` + `speak` | immediate (`didCancel` was never delivered) | `didStart` at **15.2 ms** median (p90 16.1) | ≈ 15 + ~108 (acoustic 3a minus its 3.7 ms `didStart`) ≈ **125 ms** |
| `write()` → player node, first buffer scheduled with `.interrupts` | on the next render cycle | first buffer at **20.4 ms** median (p90 29.1) | ≈ 100 ms (like 3c); ≈ 60–75 ms from a cache (3d) |

Stopping is fast on every path; restarting is what differs. With `say`, every press ends the current utterance
almost at once but starts a new ~1 s wait. That matches the field report: "only the last value was heard, and late".
To finish this acoustically, unmute and run `measure.py --only interrupt` (~70 s of sound).

## Caveats

- Built-in speaker → built-in mic only. **Bluetooth (AirPods) adds its own latency on top**, typically 100–250 ms
  plus route wake-up after silence, and it adds the tail-clipping behaviour. None of that was measured here. The
  *differences* between candidates carry over; the absolute numbers do not.
- The ~45 ms loop floor includes unreported speaker/mic DSP latency. The part of that attributable to output alone
  is unknown, perhaps 25–35 ms.
- One machine, one session, one voice (system default), modest volume in a quiet room. The `say` numbers depend
  heavily on the configured voice (see above).
- Threshold onset detection reports soft onsets (speech) a few ms later than hard ones (the tick).
- Not measured: PyObjC `AVSpeechSynthesizer` inside the Python process, which would probably match 3a without a
  companion process. The companion's pipe IPC cost is not measured separately, but it is already included: every
  Swift number above is timed from the moment Python wrote the stdin line.

## Recommendation

- **(a) Per-press ticks:** yes, in-process wins materially: **~168 ms → ~47–59 ms** (−110 to −120 ms), with a tight
  p90. A native companion isn't needed for this. A persistent `sounddevice` stream in the backend with a pre-loaded
  buffer is as fast as `AVAudioEngine` at a 128-frame IO buffer. What matters is never spawning a process per tick.
- **(b) Short spoken values:** yes, by a lot: **~960 ms → ~110 ms** (speak), **~96 ms** (render to a player node) or
  **~76 ms** (pre-rendered cache): 0.85–0.9 s less. Interruption restarts in ~15–20 ms of software time instead of
  ~1 s. Python has no in-process speech path short of PyObjC, so a small long-lived Swift companion is the
  natural home. Suggested design: one `AVAudioEngine` on the chosen device (IO buffer ~128), a tick node, and a
  speech node fed by `AVSpeechSynthesizer.write` with an LRU cache of pre-rendered values (f-numbers, shutter
  speeds, ISO). Also send ticks through the same engine so ticks and speech share one device/route. Use
  `.interrupts` for "new value supersedes old", and `.dataPlayedBack` to know when audio has really finished.
  With the 0.3 s settle timer, the spoken value would start about 0.3 s + ~80 ms after the last press on the
  built-in path, plus the Bluetooth delay on AirPods.
