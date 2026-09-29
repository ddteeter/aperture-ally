# Design brief 2: projects, shoot templates, and the at-camera additions (for a design agent)

Paste the brief below into the design agent. It extends the first brief (`docs/design-brief.md`) and the
delivered designs (`docs/design/*.dc.html`: Studio and Daylight themes, IBM Plex, glanceable from the
camera). It describes what the UI must do, not how it should look. Keep the existing design system.

```
Extend the "Aperture Ally" design (see the existing Shoot, Workflows and Design System screens) with the
features below. Same product and user: Drew, a beginner photographer reviewing running gear for a blog,
at a tethered Olympus E-M1 II, glancing at a MacBook Air 1–3 m away, wearing AirPods, holding a small
Bluetooth remote (hold L = talk, R = pause coaching, B = cancel). Studio (dark) and Daylight (bright,
outdoors) themes both required. Glanceable, calm, photo-first. Keyboard-accessible; never steal focus from
text fields.

1. THE NEW HIERARCHY (the main new idea)
Drew shoots the same kinds of product over and over, so the look and the shot lists are defined once:
- YOUR DEFAULTS: taste across all work (free text; may be empty for a long time). E.g. "I edit in Lightroom."
- PROJECT: a body of work with a consistent look. E.g. "Running blog": "Soft, blurred backgrounds that
  separate the product; warm light." Usually 1–3 projects.
- SHOOT TEMPLATE: one per product type inside a project, e.g. "Shoe review" (6 shots), "Apparel" (8),
  "Half tights", "Hat". Holds the shot list (each shot: title, purpose, must-show items, framing, 2–6
  acceptance criteria) plus preferences specific to that type ("Laces tidy, show the heel counter").
  Has a version number that goes up when a shoot's improvements are saved back to it.
- SHOOT: one product on one day, created from a template (e.g. "Pegasus 42, 28 Sep, garage"). It copies
  the template's shot list; edits during the shoot stay in the shoot until Drew chooses "Save to
  template" (update it) or "Save as new template" (e.g. turn a tights shoot into a "Hat" template). Has
  day-only notes ("Outdoors, no backdrop; overcast") that override the levels above.
The coach receives all four levels of preferences (most specific wins) and says when advice comes from a
preference ("…soft background, as you prefer").

Screens and states to design:
a) LIBRARY (where projects and templates live; could be a new top-level area or a section of Sessions —
   recommend one; tabs today are Shoot, Coverage, Shot list, Setup, Sessions, Diagnostics with ⌘1–6):
   - Your defaults (one text box, with a gentle empty state explaining what belongs there).
   - Projects list → project detail: name, preferences, its templates (name, number of shots, version,
     last used, number of shoots), actions: new project, rename, archive; new template (blank, or
     duplicate an existing one: the common way to add "Half tights" from "Apparel").
   - Template detail/editor: name, preferences, the shot list (reuse the Shot list editor's patterns),
     version and "last updated from shoot X on date".
b) NEW SHOOT flow (replaces today's New shoot form): project → template (show its shots at a glance) →
   product name → Indoor/Outdoor (starts Daylight theme) → day notes → start. Show a compact preview of
   what the coach will follow: the four preference levels, each labelled, empty ones hidden.
c) IN A SHOOT: show where it came from (Project › Template, v3) somewhere quiet; show when the shoot's
   shot list differs from its template ("2 shots changed"); "Save to template" and "Save as new
   template" with a short summary of what changes and an explicit confirm. Day notes editable mid-shoot.
d) SESSIONS list: group or filter shoots by project/template.

2. WHAT THE COACH SAW (trust and debugging, per photo)
From any photo's coach panel, open a view of exactly what was sent and returned: prompt version; the four
preference levels as applied; the camera metadata sent (aperture, shutter, ISO, lens…); whether a RAW
file was being kept; the images sent (overview + up to 3 zoomed crops, thumbnails); the instructions
(long text, collapsed by default); the raw model response (JSON, collapsed); model, latency, cost. Drew
uses this when he disagrees with advice. Read-only, desk use (not at-camera glanceable).

3. COACH PANEL ADDITIONS (at-camera)
- "Usable, but…": the verdict can be usable while still carrying one camera-side improvement ("Usable,
  but the background is busy: open to f/2.8"). Distinguish clearly from "usable, no change needed" and
  from "needs retake".
- "Probably fixable in post": a short list (e.g. "warm colour cast", "slight tilt") shown apart from the
  one main action; low emphasis.
- Speech now starts while the rest of the result is still arriving: the panel should handle the
  spoken sentence being known before the details (criteria, observations) finish loading.
- A rare "Correction:" state when the final validated advice differs from what was already spoken.

4. AUDIO SETTINGS (Coaching popover; a working minimal version exists)
Speech speed (slider, shown as words per minute and ≈× like podcasts; Drew uses ~270 wpm ≈ 1.5×), the
"photo received" sound (choice of system sound + volume), "Hear the speed" and "Hear the sound over
speech" samples. Saved per person, applied instantly.

5. MIC AND REMOTE STATUS (at-camera awareness)
The mic is the AirPods', held open for the whole shoot (so talking starts instantly); if the AirPods go
in the case the app falls back to the Mac's mic and switches back when they return. The remote (8BitDo
Micro, gamepad mode) can go to sleep. Design a quiet top-bar indicator for: mic on AirPods / on Mac mic
(fallback) / unavailable; remote connected / asleep or disconnected. Only draw attention when something
changed or is wrong. Diagnostics shows the detail (device, level, last reconnect, reason).

6. DIRECT CAMERA CONTROL (proven at the desk; design next): the app can drive the camera itself:
live view (~15 fps) for self-shots, the shutter, and aperture / exposure compensation / ISO / focus mode
from the remote (tested: D-pad up/down = aperture in 1/3 stops, left/right = compensation, A = shutter,
X = read out settings; L/R/B stay talk/pause/cancel) or by voice, plus "apply the coach's suggestion" in one
press. Owner feedback from the test: rapid presses must not each start speaking (only the last was heard,
late). Design for: a short tick per step (a different one at the end of the range), the value spoken once
~0.3 s after the last press, and a large transient on-screen readout of the value being changed. Also a
connection state for the camera (connected / waiting / camera asleep) and a clear "release camera" when
switching back to OM Capture.

Deliver: screens for 1a–d, 2, 3, 4, 5 in both themes; empty, loading and error states; a note on where
Library lives in the navigation and keyboard shortcuts for anything new.
```
