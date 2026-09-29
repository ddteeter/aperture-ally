#!/usr/bin/env bash
# Build "Aperture Ally.app": the menu-bar app that runs the server, shows the UI and speaks in-process.
# Usage: scripts/build-mac-app.sh [--install]   (--install copies it to /Applications)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$ROOT/macos/ApertureAlly"
APP="$ROOT/build/Aperture Ally.app"
(cd "$PKG" && swift build -c release)
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$PKG/.build/release/ApertureAlly" "$APP/Contents/MacOS/ApertureAlly"
sed "s#__REPO__#$ROOT#" "$PKG/Resources/Info.plist" > "$APP/Contents/Info.plist"
[[ -f "$ROOT/frontend/dist/index.html" ]] || (cd "$ROOT/frontend" && npm ci && npm run build)
codesign --force --sign - "$APP"   # ad-hoc: fine for this Mac; notarize only to distribute
echo "built $APP"
if [[ "${1:-}" == "--install" ]]; then
  rm -rf "/Applications/Aperture Ally.app"
  cp -R "$APP" /Applications/
  echo "installed /Applications/Aperture Ally.app"
fi
