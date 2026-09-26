#!/usr/bin/env bash
# All routine (non-paid) checks: lint, backend tests, frontend typecheck/unit/build, e2e.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/backend" && uv sync --frozen && uv run ruff check . && uv run pytest -q)
(cd "$ROOT/frontend" && npm ci && npm run typecheck && npm test && npm run build && npm run e2e)
