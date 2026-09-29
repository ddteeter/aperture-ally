#!/usr/bin/env bash
# Regenerate the raster icons from the design's SVGs (docs/design/icons, mark 2a). Needs rsvg-convert
# (brew install librsvg). Outputs are committed, so building the app doesn't need this.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/docs/design/icons"
RES="$ROOT/macos/ApertureAlly/Resources"
TMP="$(mktemp -d)"
ICONSET="$TMP/AppIcon.iconset"
mkdir -p "$ICONSET"
# macOS icons sit on Apple's grid: the tile is 824/1024 of the canvas, centred, so it matches other apps in the
# Dock (the design's SVG fills the whole canvas).
icon() {  # icon <canvas px> <out>
  local c=$1 t=$(( $1 * 824 / 1024 ))
  rsvg-convert -w $t -h $t "$SRC/app-icon.svg" -o "$TMP/tile.png"
  magick "$TMP/tile.png" -background none -gravity center -extent ${c}x${c} "$2"
}
for s in 16 32 128 256 512; do
  icon $s "$ICONSET/icon_${s}x${s}.png"
  icon $((s*2)) "$ICONSET/icon_${s}x${s}@2x.png"
done
iconutil -c icns "$ICONSET" -o "$RES/AppIcon.icns"
# Menu-bar template image: the single-colour mark (black; macOS tints it), 18 pt at 1× and 2×, with the wider
# blade gaps the design uses below 24 px (favicon.svg's 4.5 instead of 3.5).
sed -e 's/currentColor/#000000/g' -e 's/stroke-width="3.5"/stroke-width="4.5"/' "$SRC/mark-mono.svg" > "$TMP/mark-black.svg"
rsvg-convert -w 18 -h 18 "$TMP/mark-black.svg" -o "$RES/StatusIcon.png"
rsvg-convert -w 36 -h 36 "$TMP/mark-black.svg" -o "$RES/StatusIcon@2x.png"
# Web: home-screen / bookmark icon.
rsvg-convert -w 180 -h 180 "$SRC/app-icon.svg" -o "$ROOT/frontend/public/apple-touch-icon.png"
rm -rf "$TMP"
echo "icons written to $RES and frontend/public"
