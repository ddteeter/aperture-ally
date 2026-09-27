# Design brief (for a design agent)

Paste the brief below into a design tool/agent. It describes what the UI must do, not how it should look.

```
Design a polished UI for "Aperture Ally", a local-first macOS web app (React + TypeScript + Vite,
plain CSS, served on localhost) that coaches a beginner photographer *during* a shoot.

WHO & WHERE
Drew reviews running apparel (mostly) and shoes for a blog. He shoots with an Olympus E-M1 II tethered
to a MacBook Air. He is usually standing at the camera 1–3 m from the laptop, glancing at the screen
between shots, wearing headphones. The coach speaks to him; he replies by holding a push-to-talk
remote button. The screen must be readable at a glance from a distance, calm and uncluttered, and must
never compete with the photo. Think "photo tool" (Lightroom / Capture One sensibility), not SaaS dashboard.

THE CORE LOOP (most important screen: "Shoot")
1. Drew picks the active shot from a shot list (e.g. "Fabric close-up": purpose, must-show items,
   2–3 acceptance criteria).
2. He takes a photo. It appears within ~1 s. Show a clear "Received #12" moment. He can draw up to 3
   rectangles on the photo marking what must be sharp; the app shows zoomed crops of those regions.
3. A few seconds later the coach verdict arrives: needs retake / usable candidate / uncertain. It includes
   one main action ("Move the light a hand-width camera-left"), a short why, the expected effect, the
   tradeoff, and pass/fail/uncertain per criterion. The same text is spoken aloud.
4. Drew changes something (spoken or typed "what I changed") and retakes. The next photo is compared with
   the previous one: improved / worse / mixed / uncertain, with before/after side by side.
5. He rates the advice (helpful / neutral / harmful) and notes the lesson in his own words.
6. When happy, he explicitly accepts a keeper for that shot (a deliberate confirm; AI never auto-accepts).
Also on this screen:
- analysis-in-progress state;
- failure states (AI unavailable, bad file), each with a retry;
- a filmstrip of all photos with small status badges;
- a coaching on/paused control with budget usage (paid calls used / cap, estimated $);
- a voice bar showing listening, transcribing, thinking or speaking, plus the last question and answer.

OTHER WORKFLOWS
- Sessions: create a shoot (name, product, template, AI provider, watch folder, teaching mode); list and
  reopen past shoots.
- Setup: light type (continuous/flash/natural), movable or fixed light, tripod or handheld, manual or auto
  exposure/ISO, gear available. It is versioned and editable mid-shoot.
- Shot list editor: add, edit or reorder shots and their criteria.
- Coverage: per shot, missing / candidate / needs retake / accepted keeper (with thumbnail); an export
  (JSON, Markdown, contact sheet). This is the "am I done?" view before packing up.
- Diagnostics: health checks, remote-key test ("press your button"), timings, mock controls. Functional
  and secondary; keep it simple.

DATA & STATES TO DESIGN FOR
- Measurements: small luminance histogram, clipping %, relative sharpness per region, with honest
  caveats.
- Camera settings: shutter, f-number, ISO, lens (may be missing; never invent values).
- Honesty labels: "MOCK PROVIDER" and "SIMULATED" sessions must be unmistakable.
- Verdict and outcome colours must also carry text or icons (never colour alone).
- Long lists of photos; empty states; no-network state.

TEACH THE HISTOGRAM, DON'T JUST SHOW IT
Drew doesn't know how to read histograms. Wherever brightness data appears, explain it in plain
language and tie it to the photo and to an action:
- One-sentence headline computed from the data, e.g. "Mostly mid-tones; 4% of the mesh is pure white
  (detail lost there)." Colour-code it by severity, with text or icons as well as colour.
- Label the graph's zones directly on it: shadows / mid-tones / highlights, plus the "clipped" edges at
  each end. Include a small "how to read this" explainer that can be expanded, not a wall of text.
- Link graph ↔ photo both ways: hovering or tapping a zone highlights those pixels on the photo
  (e.g. a zebra/red overlay for clipped highlights); hovering a region shows that region's histogram.
- The histogram of each marked region matters more than the whole frame. Show it first.
- Give context, not rules: "A white shoe on a white background *should* lean right; that's fine" versus
  "the fabric's highlights are clipped, so texture is gone". There is no single "correct" shape.
- Connect it to the coaching: when the coach's advice is about exposure or glare, point at the part of
  the graph and the part of the photo it's talking about.
- Before/after: overlay the previous attempt's histogram so Drew sees what his change did.
- Caveat in small print: this reflects the processed JPEG, not the RAW file (RAW may hold more detail).

DELIVERABLES
- A small design system: colour tokens (dark theme first, since photo work looks best on neutral dark
  greys; light theme optional), type scale with an extra-large glance size, spacing, and components
  (chips, cards, buttons, image frames, region overlays, before/after, voice bar).
- High-fidelity mocks of Shoot (idle, analysing, needs retake, comparison improved, failure, paused),
  Coverage, Sessions/create, and the shot and setup editors.
- Notes on layout at 1440–1680 px laptop width, keyboard focus, and accessible contrast.
The photo is the hero; chrome should recede. Keep it implementable in plain CSS.
```

## Data the app already provides (for the implementer)

Per photo (`GET /api/sessions/{id}` → `captures[]`, and `GET /api/captures/{id}`):
- `histogram_insights`: `summary` (one line), `regions[]` then `overall`, each with `headline`, `shape`,
  `severity` (`problem|warn|info|ok`), `zones` (share of shadows / mid-tones / highlights),
  `highlight_clip`, `shadow_clip`, and `findings[]` (`zone`: `clip_low|shadows|midtones|highlights|clip_high`,
  `headline`, `detail`); plus `how_to_read[]` and `caveat`.
- `evidence.measurements.global.histogram` and `...regions[id].histogram`: 64 bins, dark to bright.
- `GET /api/captures/{id}/image/clip_overlay`: transparent PNG at overview size (red = pure white,
  blue = pure black), generated on first request.
- `histogram_changes`: `{baseline_seq, changes[]}`, plain sentences about what the retake changed.

Known layout issue in the current UI: the fixed voice bar covers content while scrolling.
