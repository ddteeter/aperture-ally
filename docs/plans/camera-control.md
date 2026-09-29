# Plan: direct camera control (step 3)

Status: proposed 2026-09-29. Builds on the direct-control spike (branch `spike/camera-control`,
`docs/local-verification-results.md` → "Direct control spike"), the button map (`remote-button-map.md`), the
native-audio results (companion app speech) and the Shoot v2 design, group 6 "Camera control".

## Goal

With the E-M1 II on USB and OM Capture closed, the app owns the camera:

- settings from the 8BitDo Micro, with a tick per step and the value spoken once when you stop;
- the shutter from the remote (A);
- live view on the stage;
- the coach's suggestion applied with one press (Y);
- photos landing in the shoot within ~0.6 s of the "photo taken" event, and still coached as today.

OM Capture stays a supported fallback: if it has the camera, or you release the camera to it, photos keep
arriving through the watch folder.

## Decisions (owner, 2026-09-29)

- **Take control automatically** when a shoot is open, the camera is on USB and OM Capture isn't holding it.
  The app says so; ⌘K releases to OM Capture and takes it back.
- **First-photo delay: just say it** ("reading the card, about 10 s"). No card or capture-target changes.
- **L toggles live view** (as designed). Daylight moves to **D**.

## Shape

```
8BitDo Micro ──hid──▶ GamepadListener ──▶ RemoteActions ──▶ CameraService ──▶ camera thread (python-gphoto2)
                                              │                  │                     │
                                   ticks + spoken value     bus events           downloads JPEG/ORF
                                   (companion app)      camera.* → UI (WS)    into the shoot's watch folder
                                                                                       │
                                                                     existing ingest → coaching (unchanged)
```

- **One thread owns the camera.** libgphoto2 is blocking and not thread-safe, so a dedicated worker thread
  holds the `gp.Camera`. It takes commands from a queue (set, trigger, preview frame, release) and pumps events
  between commands. Everything else talks to it through `CameraService` (async).
- **Only `camera/gphoto.py` imports gphoto2.** A `FakeCamera` with the same small interface drives every
  test, so all logic is tested without hardware.
- **Photos go through the existing pipeline.** On `FILE_ADDED` the worker downloads straight into the active
  shoot's watch folder under our own unique name (`AA_<seq>.JPG/.ORF`). The ingest's fast-ready path picks it
  up as it does for OM Capture. Bracket tags, pairing, keepers and coaching are unchanged.
- **Settings step through the camera's own choice lists** (read once at connect: aperture f/1.0…f/91, ISO
  with Auto, compensation ±5 in ⅓ steps). "End of range" is the first/last choice. Aperture is clamped to what
  the mounted lens reports: the list the camera gives is the lens's range.

## States (what the top bar, stage and panel show)

`absent` (no camera on USB, re-checked every 2 s) → `connecting` (~2.7 s) → `connected` (you control it) ⇄
`asleep` (the camera powered off; reconnects when it wakes) · `busy_elsewhere` (OM Capture or another app has
it) · `released` (you gave it to OM Capture; ⌘K takes it back) · `error` (message + retry).

## Tasks (each a commit)

1. **Dependency and config.** Add `gphoto2` (PyPI wheel bundles libgphoto2) and `APERTURE_ALLY_CAMERA=off|direct`
   (default `off` until task 11 passes, then `direct`). Doctor check: wheel importable, camera visible on USB,
   OM Capture running.
2. **`camera/gphoto.py`**: connect, `get`/`set` single config, choice lists, `trigger`, `preview` (JPEG
   bytes), `wait_event` (parsed like the spike's `camlib`), `download(folder, name, dest)`, `release`.
   Carry the spike's known traps over: skip prop `d405` (segfault), never read the full config tree.
3. **Release on exit.** The spike left the camera locked until the cable was unplugged. Find the call that
   hands control back (libgphoto2's Olympus "camera control off" on `exit()`, else the PC-mode prop `0xD052`
   set back), verify it with the owner, and call it on release, on app quit (SIGTERM) and on crash where
   possible. Blocking for task 11.
4. **Camera worker + `CameraService`**: thread, command queue, event pump, state machine, reconnect with
   backoff, settings cache updated from `PTP Property changed` events (so dial changes on the body show up),
   downloads into the watch folder, bus events (`camera.state`, `camera.setting`, `camera.photo`). Tests with
   `FakeCamera`: steps, end of range, reconnect, download naming, release.
5. **Remote → camera.** Extend the gamepad map: D-pad ↑↓ aperture, ←→ compensation, ZL/ZR ISO (Auto at the
   bottom), A shutter, Y apply, + read-out. Holding a D-pad direction repeats after 0.4 s at ~6 steps/s.
   L/R/B are unchanged. When there's no camera, camera buttons give a short "no camera" tone instead of
   silence.
6. **Feedback sounds via the companion app.** Add a `cue` op to the companion (preloaded short sounds played
   in-process, ~50 ms instead of ~170 ms for `afplay`): `tick` per step, a lower `tock` at the end of the range.
   Speak the value once 0.3 s after the last press ("f two point eight", "plus two thirds", "ISO auto");
   a new press cancels speech that hasn't started. Falls back to `afplay`/`say` without the companion.
7. **API**: `GET /camera` (state, settings, choices, lens range), `POST /camera/take`, `/camera/release`,
   `/camera/step {setting, dir}`, `/camera/set {setting, value}`, `/camera/trigger`, `/camera/apply`,
   `/camera/readout`; live view `GET /camera/live` as an MJPEG stream (multipart), only while a client watches.
8. **Apply the coach's suggestion (Y / "apply it").** Needs a machine-readable change from the coach. Add an
   optional `camera_change {setting, value}` to the result schema (aperture, exposure compensation, ISO only).
   The prompt fills it only when the one action is a single setting change. This changes the prompt; check it
   on shoot-1 data before relying on it. Until then, Y applies `exposure_note.new_f_number` when present,
   and says "nothing to apply" otherwise. Side effects are spoken and toasted ("shutter moved to 1/500 s").
9. **UI (Shoot v2, group 6)**:
   - live view on the stage, with the settings along the bottom edge;
   - a big readout on change (fades 1.5 s after the last press);
   - L toggles live view (Daylight moves to D);
   - the panel in camera mode: connection box with Release ⌘K, a settings grid labelled with remote buttons,
     the coach's suggestion with Apply (Y), a remote legend;
   - the Waiting and Asleep stage states;
   - a Release dialog listing what stops and what keeps working;
   - a camera chip in the top bar;
   - real data in the Diagnostics camera card.
10. **First-photo delay** (libgphoto2 lists every file on the card on the first photo: ~10 s with ~700
    files). Say it rather than hide it: "First photo on this connection: reading the card, about 10 s"
    (owner's choice; no card or capture-target changes).
11. **Owner session at the camera** (checklist below). Then default `APERTURE_ALLY_CAMERA=direct`, update
    `docs/setup.md`, `POC_STATUS.md` and the results doc.

## What needs you at the camera (task 11), prepared as a run sheet when we get there

1. 30-second press test of ZL, ZR, +, −, Home, ★ in S mode (untested so far).
2. Release: quit the app with the camera connected, then check the camera's own buttons work without unplugging.
3. Settings from the remote: aperture across the whole range (end-of-range tock), compensation, ISO including
   Auto; say whether the tick/spoken feedback feels right.
4. Shutter from A, from the camera's own button, a burst and an AE bracket: every JPEG+ORF arrives and is
   coached; bracket frames are tagged.
5. Sleep: let the camera auto-power-off, wake it, and check it reconnects.
6. Y applies a suggestion; live view on the stage.

## Not in this plan

Shutter speed in S/M (untested in the spike), focus/drive/bracket settings, changing card or capture-target
settings without asking, and Wi-Fi control.
