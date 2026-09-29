# Aperture Ally — icon set (mark 2a, "The blade that speaks")

| File | Use |
|---|---|
| mark-on-dark.svg | Logo mark on dark UI (#161616 and darker) |
| mark-on-light.svg | Logo mark on light / daylight UI |
| mark-mono.svg | Single colour, inherits `currentColor` (inline in HTML) |
| app-icon.svg | 1024² app icon, dark tile (primary) |
| app-icon-light.svg | 1024² app icon, light tile |
| favicon.svg | 16–32px; wider blade gaps; switches with prefers-color-scheme |
| favicon-on-light.svg / favicon-on-dark.svg | Fixed-colour favicon variants (no media query) |

Gaps between blades are real transparency (SVG mask), so marks work on any background.

## Colours
- Dark: blades #ececec, speaking blade #79c0e8 (≈ oklch(0.80 0.10 230), app accent)
- Light: blades #0a0a0a, speaking blade #1a7bb0 (≈ oklch(0.55 0.13 230))

## Rules
- Only the speaking blade (lower-left, with tail) takes the accent. Never recolour other blades.
- Don't rotate the mark — the tail must point lower-left.
- Minimum size 16px (use favicon.svg below 24px). Clear space = one blade width on all sides.

## Wordmark
"Aperture Ally", IBM Plex Sans 600, letter-spacing −0.01em. Mark height = 1.7× cap height, gap = 0.55× mark height.
