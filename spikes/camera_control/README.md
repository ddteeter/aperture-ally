# Spike: direct USB control of the E-M1 Mark II (no OM Capture)

Throwaway code, measured 2026-09-28 on the owner's Mac (Apple silicon, macOS 26) with the
E-M1 Mark II (USB `07B4:0130`, USB 2.0, "camera → screen" PC-control mode), battery 100 %,
OM Capture closed.  Scene: a very dark room (ISO 6400, 0.4–5 s exposures).

**Library:** `python-gphoto2` 2.6.4 from PyPI.  It ships a macOS arm64 wheel for Python 3.12
with **libgphoto2 2.5.34 bundled** (`gphoto2/.dylibs`, camlibs inside the wheel), so no
Homebrew, ctypes or subprocess is needed.  The spike runs outside the backend project
(`uv run --no-project --python 3.12 --with gphoto2 …`); nothing in `backend/` was changed.

## Results

| # | Question | Result |
|---|---|---|
| 1 | Connect once, keep it | **PASS**. `camera.init()` = **2.65 s** median (10 connects: 2.65–3.0 s, one 9.8 s outlier). ~1.65 s of it is libgphoto2 sleeping after switching the camera to PC mode (`0xD052`). Held one connection for 5 min idle: see *Idle hold* below |
| 2 | Get/set settings | **PASS except shutter in A mode** (table below). Every value restored and verified |
| 3 | Remote trigger + immediate JPEG+ORF | **PASS**. Both files downloaded for every trigger; steady state **c101 → JPEG ≈ 1.0–1.35 s, c101 → ORF ≈ 1.9–2.2 s, trigger → both ≈ 3.75 s** (0.4 s exposure). **First photo of a connection is ~5.5 s later** (card enumeration, see below) |
| 4 | Live view in-process | **PASS**. **14.9 fps**, median 61 ms/frame (p95 103 ms, max 114 ms), 1024×768, ~86 kB JPEG. vs 6 fps with `--capture-movie` and 3.1 s/frame via the CLI |
| 5 | Where remote photos go | **PC and SD card.** Capture target is Olympus prop **`0xD0DC`** (libgphoto2 `PTP_DPC_OLYMPUS_CaptureTarget`), menu {3, 2, 1}, current **2**. Remote shots appear as objects in the card storage `0x00010001` at `/DCIM/100OLYMP/_928NNNN.{JPG,ORF}` with the card's running file number (583 → 588 across runs). Not changed |

### 2. Settings (one connection, `get_single_config` / `set_single_config`)

| Setting | Original | Set to | Read back | set call | until camera reports it | Restored |
|---|---|---|---|---|---|---|
| aperture | 8.0 | 5.6 | 5.6 | 15 ms | 20 ms | yes |
| shutterspeed | 2 (s) | 1/125 | **2 (ignored)** | 25 ms | never | yes (n/a) |
| iso | Auto | 200 | 200 | 20 ms | 17 ms | yes |
| exposurecompensation | 0 | +0.7 | 0.7 | 30 ms | 23 ms | yes |
| focusmode | Automatic | Manual | Manual | 84 ms | 27 ms | yes |
| imageformat | Large Fine JPEG+RAW | Large Fine JPEG | Large Fine JPEG | 39 ms | 33 ms | yes |

Shutter speed: the camera is on **A (aperture priority)** (EXIF `ExposureProgram`), where the
camera owns the shutter; the write is accepted and silently ignored.  Expected to work in S/M,
**not verified** (needs the mode dial).  Reads are ~2 ms each.  Changes are pushed back as
`PTP Property d0xx changed` events, e.g. the metered shutter speed (`0xD01C`) after an aperture change.

### 3. Remote trigger (4 measured shots, aperture 1.8 temporarily, ISO Auto → 6400, 0.4 s)

| Shot | trigger → AF (c103) | trigger → c101 | c101 → JPEG on disk | c101 → ORF on disk | trigger → both |
|---|---|---|---|---|---|
| 1 (first of connection) | 292 ms | 1552 ms | **6430 ms** | **7302 ms** | **8854 ms** |
| 2 | 275 ms | 1903 ms | 968 ms | 1850 ms | 3753 ms |
| 3 | 285 ms | 1525 ms | 1345 ms | 2227 ms | 3752 ms |
| 4 | 275 ms | 1787 ms | 1132 ms | 1998 ms | 3785 ms |

Transfers: JPEG 8.2 MB in 366–452 ms, ORF 18.8 MB in 858–873 ms (≈ 21–22 MB/s, the USB 2 ceiling).
`trigger_capture()` returns in 5–17 ms.

**Event sequence per shot** (every event logged in `trigger.jsonl`):
`trigger` → `0xC103` AF_Frame(p1=1) ~0.28 s → *(exposure)* → `0xD124`→1 → **`0xC101` CreateRecView_New**
→ `0xC103` AF_Frame(p1=3) → **`0xC102` ObjectAdded_New(p1=handle of the JPEG)** 0.5–0.9 s after c101
→ libgphoto2 returns `FILE_ADDED …/_928NNNN.JPG` → (we download) → `FILE_ADDED …/_928NNNN.ORF` ~10 ms after
the JPEG download.  `0xC105` ComplateCameraControlOff_New appears **on every connect** (param 0), so
the lone c105 seen in the CLI test is not a shutter press.  No `CaptureComplete` (0x400D) is sent.
Property noise: `0xD084` and `0xD062` change constantly (filtered from the console, kept in logs).

**Why the gphoto2 CLI was slow and the first shot here is slow.** libgphoto2 handles the Olympus
`0xC102` by calling `add_object_to_fs_and_path`, which on first use of the card folder lists it and
fetches `GetObjectInfo` for **every file in `/DCIM/100OLYMP` (711 files ≈ 7 s)** before returning
`FILE_ADDED`.  The folder is then cached, so later shots on the same connection are fast.  It can't be
pre-warmed: in PC mode `folder_list_folders("/")` lists no storage and `/store_00010001/...` is
"Directory not found" until the first object arrives.  Cost scales with files on the card.

### 4. Live view (10 s, `capture_preview()` in a loop, no reconnects)

| Frames | fps | first frame | median | p95 | max | size |
|---|---|---|---|---|---|---|
| 150 | **14.9** | 111 ms | 61 ms | 103 ms | 114 ms | 1024×768, 86 kB |

libgphoto2 switches live view on by writing `0xD06D` = `0x04000300`; we write the original (0) back afterwards.

### Idle hold

**PASS, no drop-off.** One connection held **300 s** idle (events pumped every 200 ms, battery read
every 10 s): **0 errors, no reconnect needed**, battery 100 % throughout.  The camera did not sleep
while tethered and polled.  Earlier today the camera fell off the USB bus completely (not even in
`ioreg`) while *not* connected; that path (sleep → re-enumeration) was not reproduced here.
`camera_button_test.py` and `idle_test.py` reconnect on a `GPhoto2Error` and log the downtime.

### Camera-button presses (not run: needs the owner)

`camera_button_test.py` is ready.  Based on the event handling above, a camera-button press should
look the same as a remote trigger (c101 → c102 → FILE_ADDED), because the files are real card objects
and the pump downloads every `FILE_ADDED` immediately.  The CLI test's missing ORF matches the CLI
fetching late and stopping; not yet proven for the button.

```
cd spikes/camera_control
uv run --no-project --python 3.12 --with gphoto2 python camera_button_test.py --singles 3 --burst 4 --bracket 5
```

It walks the owner through three phases (Enter to start/stop each): singles, one held burst
(Sequential L), and an AE bracket; logs every event; downloads JPEG+ORF per frame to
`$TMPDIR/camera-spike/button-<time>/`; reports presses vs expected, files per frame, c101→JPEG/ORF
latency, missed ORFs and the `Olympus:DriveMode` bracket tag per frame; reconnects if the camera drops.

## Open questions / risks

1. **First-shot enumeration** (~10 ms per file in the card folder).  Options: keep the card folder small
   (offload/format between sessions); take one throwaway shot at session start; try capture target
   "PC only" (`0xD0DC` = 3 or 1, not tested, the owner must agree to a card-setting change); or patch
   libgphoto2 to skip the folder listing.
2. `0xD0DC` values are inferred (2 = PC+card from behaviour); 1 and 3 untested.
3. Shutter-speed writes in S/M mode untested; there is no exposure-mode (P/A/S/M) widget, it's the dial.
4. Bracketing props `0xD110`/`0xD111` still undecoded (libgphoto2 names them AEBracketingFrame/Step for
   older E-series).  Frames can be tagged after download from `Olympus:DriveMode` instead.
5. Reading the full config tree **segfaults** in python-gphoto2 when `get_value()` hits the NULL text prop
   `0xD405`: use `get_single_config` (as here) or skip `d405`.
6. Burst/bracket throughput: each frame is ~27 MB at ~22 MB/s over USB 2, so a 5-frame bracket needs
   ~6–7 s to download.  Only one USB program at a time (OM Capture must be closed).

## Files

- `camlib.py`: connection, config get/set, event parsing, `Pump` (download every `FILE_ADDED` now), shutter budget
- `probe.py`: connect time ×3, originals, capture-target/bracket props (read-only)
- `settings_test.py`, `liveview_test.py`, `trigger_test.py N [--aperture 1.8]`, `idle_test.py SECONDS`
- `explore_trigger.py`, `explore_debug.py`: the two exploratory shots (the second with libgphoto2 debug logging)
- `camera_button_test.py`: interactive owner test (not run)

Photos and logs went to `$TMPDIR/camera-spike` only and were deleted at the end.  Shutter fired 6 times
(2 exploratory + 4 measured).
