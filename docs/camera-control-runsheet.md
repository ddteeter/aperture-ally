# Run sheet: direct camera control at the desk (plan task 11)

About 20 minutes with the E-M1 II, a USB-C cable, the 8BitDo Micro (S mode) and AirPods. Claude runs the Mac side
and records results in `docs/local-verification-results.md`. Nothing here changes card or capture-target
settings; the shutter fires roughly 15 times.

## Before (Claude)

- Rebuild and reopen Aperture Ally.app (it has the new `cue` op for ticks).
- Set `APERTURE_ALLY_CAMERA=direct` in the local `backend/.env` (never committed).
- `aperture-ally doctor`: gphoto2 imports; OM Capture closed.

## At the camera (you), in order

1. **Connect.** Quit OM Capture. Plug in USB, switch the camera on, choose the PC-control USB mode. Expected: the
   top bar shows "◎ You control" within ~3 s; Diagnostics shows the camera card connected.
2. **Buttons nobody has pressed yet** (30 s). Press ZL, ZR, +, −, Home and ★ once each, slowly. Claude reads
   which names arrive.
3. **Settings from the remote.** On the Shoot screen press L for live view.
   - D-pad ↑ repeatedly to the widest aperture: a tick per press, a different sound at the end, and the
     value spoken once when you stop. Then ↓ a few times.
   - ← / → for compensation; ZL / ZR for ISO, down to Auto.
   - Hold ↑ for a second: it repeats, and stops at the end.
   - Say whether the ticks and the spoken value feel right, and whether the body's display matches.
4. **Shutter.** Press A. The first photo of the connection is slow (~10 s while the card is read; the coach
   says so). Then A three more times: each photo should appear and be coached within ~1–2 s.
5. **The camera's own buttons.** Take two shots with the body's shutter button, a short burst, and a 3-frame AE
   bracket: every JPEG and ORF should arrive, with bracket frames tagged.
6. **Apply (Y).** After a verdict that changes the aperture, press Y: "f …, applied", and the body changes.
7. **Release and hand-back.** Press ⌘K → Release camera. **Then check the camera's own buttons and dials
   work without unplugging** (the spike left it locked). Press ⌘K again to take it back.
8. **Quit with the camera connected.** Quit Aperture Ally from the menu bar, then check the camera's buttons
   again without unplugging.
9. **Sleep.** Let the camera auto-power-off (or switch it off and on). It should show "Camera asleep", then
   reconnect by itself when it wakes.

## Pass criteria

- Every step's feedback arrives with no queueing: one spoken value per burst of presses.
- No missed JPEG or ORF; bracket frames tagged.
- After release and after quitting, the camera's own controls work without pulling the cable. If they don't,
  Claude tries the alternatives for the hand-back (plan task 3) with you then and there.
- Reconnects after sleep without restarting the app.

Then `APERTURE_ALLY_CAMERA=direct` becomes the default, and the setup docs, `POC_STATUS.md` and the results doc
are updated.
