#!/usr/bin/env bash
# One-command local launch: sync deps, build the UI if needed, start the app on http://127.0.0.1:8765
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
command -v uv >/dev/null || { echo "uv not found: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
command -v npm >/dev/null || { echo "npm not found: brew install node"; exit 1; }
(cd "$ROOT/backend" && uv sync --frozen)
if [[ ! -f "$ROOT/frontend/dist/index.html" || "${REBUILD_UI:-0}" == "1" ]]; then
  (cd "$ROOT/frontend" && npm ci && npm run build)
fi
cd "$ROOT/backend"
[[ -f .env ]] || echo "note: no backend/.env — using mock provider/speech/mic (copy .env.example to configure)"
exec uv run aperture-ally serve "$@"
