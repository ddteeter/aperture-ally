# 8BitDo Micro (S mode) button map

Decided with the owner on 2026-09-28. Supersedes the design brief's assumption that Y was the only free button.

| Button | Action | Notes |
|---|---|---|
| L (hold) | talk to the coach | built, tested |
| R | pause / resume coaching | built, tested |
| B | cancel speech / recording | built, tested |
| D-pad ↑ / ↓ | aperture wider / narrower (1/3 stop) | tested in the demo |
| D-pad ← / → | exposure compensation − / + | tested in the demo; this is how brightness is set in A mode |
| L2 / R2 | ISO down / up; **Auto** sits at the bottom of the range | in A mode ISO changes the shutter speed the camera picks (noise vs blur), not brightness |
| A | shutter | tested in the demo |
| Y | apply the coach's suggestion (voice: "apply it") | the designer's proposal, kept |
| + (Start) | read out the current settings | moved from X |
| X | repeat the last advice (keyboard R) | added 2026-09-29 at the owner's request |
| − (Select) | unassigned in the app (quit in the demo) | |
| Home, ★ | unassigned | one of them switches the Micro's modes; test first |

**Untested in S mode:** L2, R2, +, −, Home and ★ are decoded by the Switch Pro layout but haven't been pressed on
this Micro. Do a 30-second press-each-button check before relying on them.

**Feedback:** each step gets a tick (a different one at the end of the range); the final value is spoken once,
~0.3 s after the last press (docs/local-verification-results.md, native audio spike).
