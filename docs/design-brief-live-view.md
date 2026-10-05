# Design brief 3: full-screen live view with overlays

For the design agent (Claude Design). Builds on Shoot v2 group 6 ("Camera control") and the design system.
Written 2026-09-29 after the first session with direct camera control on the real camera.

## Why

Direct control works: the app shows the E-M1 II's live view, and the 8BitDo Micro changes aperture, exposure
compensation and ISO, and fires the shutter. But at the camera the photographer is **1–3 m from the Mac** and
often behind the camera. In the current layout (shot rail + stage + coach panel) the live view is about half
the screen, so it's too small to judge framing, focus or background from there. The owner wants live view to go
**mostly full screen, with transparent overlays for the key information**.

## Facts to design around

- Live view is **4:3, 1024×768 JPEG, ~13 fps** (the camera's preview). The Mac is a 13"/15" MacBook Air, usually
  full screen in the Aperture Ally app window (1470×956 points on the 15").
- Two themes: **Studio** (dark, indoors) and **Daylight** (outdoors, bright screen). Overlays must stay readable
  on any photo content in both.
- **L** toggles live view. After a shot the new photo and its verdict show, then live view **returns by itself**
  ~2 s after the verdict is spoken. Any remote camera button returns at once (built; see "Live view returns
  after the verdict" note in the app).
- Remote (no keyboard at the camera): L hold = talk · R pause coaching · B cancel · D-pad ↑↓ aperture · ←→
  exposure comp · ZL/ZR ISO · A shutter · Y apply the coach's suggestion · + read out settings · X repeat advice.
- Feedback already exists and should keep its place: the **big readout** (value in huge mono type, tick bar
  showing position in range, "end of range") while changing a setting; ticks and a spoken value.

## What should be on screen in full-screen live view (propose a hierarchy; not all at once)

1. The picture, as large as possible (letterboxed 4:3; say what goes in the side bars on a 16:10 screen).
2. Current settings: aperture, shutter, ISO, compensation (+ which one just changed).
3. The active shot: name, and optionally its framing note / must-show items as a quiet reminder.
4. The coach: the last spoken line, and whether it's speaking / listening / thinking (voice state).
5. The coach's pending suggestion (e.g. "Open to f/2.8 · Y applies").
6. Device state only when something's wrong (mic, remote, camera asleep).
7. Optional composition aids worth considering: rule-of-thirds grid, level/horizon, centre mark. Say which are
   worth it at 1–3 m and how they're toggled with no keyboard (or leave them out).

## The moments to design (states)

- Idle live view (you're framing).
- Changing a setting (readout visible over live view).
- Talking to the coach (holding L) and the coach answering.
- Just after a shot: how the photo + verdict appear full screen, and how it transitions back to live view
  (including the ~5 s "returning" moment and a way to keep it longer, if that's needed).
- Something wrong: camera asleep, remote asleep, mic fell back to the Mac.
- Getting in and out of full screen, from the keyboard at the desk and from the remote at the camera.
- Daylight versions of the main states.

## Constraints

- Follow the design system: IBM Plex Sans/Mono, the token colours, one accent, glyph + word for states (never
  colour alone), and the honesty rules (MOCK/SIMULATED labels must stay visible).
- Overlays must never hide the middle of the frame for long; the readout is the only thing allowed there, briefly.
- Text sizes readable at 1–3 m (the stage's current glance sizes are the reference).
- Only − is free on the remote (Home/★ may switch the remote's mode; avoid).

## Deliverables

A "Live view full screen" page in the design project with the states above (Studio and Daylight), design notes
per state, and any new tokens. Say explicitly what changes in the existing Shoot v2 group-6 screens.

## Decisions after the design agent's first pass (owner, 2026-09-29)

- **Grid and level are on by default** (the owner's preferred default); turned off/on by voice. The level shows
  only if the camera reports one over USB (unverified; probe the property list at the next camera session).
- **+** reads out the settings and shows the framing note again.
- Shutter hint "A-mode" is right (aperture priority: the camera picks the shutter).
- Remote X now repeats the last advice; only − is free.
