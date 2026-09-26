# Aperture Ally — frontend

Plain React 19 + TypeScript + Vite UI for the Aperture Ally backend (no UI kit, no router; hash tabs
`#shoot`, `#coverage`, `#diagnostics`, `#sessions`).

## Scripts

| Script | What it does |
| --- | --- |
| `npm run dev` | Vite on http://127.0.0.1:5173, proxying `/api` (incl. the `/api/events` WebSocket) to `http://127.0.0.1:8765`. Override the target with `APERTURE_ALLY_BACKEND=http://127.0.0.1:XXXX`. |
| `npm run build` | `tsc -b && vite build` → `dist/`. The backend serves `frontend/dist` at `/` and `/assets` when `dist/index.html` exists. |
| `npm test` | Vitest (jsdom) unit/render tests in `src/**/*.test.ts(x)`. |
| `npm run typecheck` | `tsc -b` (no emit). |
| `npm run e2e` | Playwright tests in `e2e/` (see below). |

Start the backend first for `dev` (`cd ../backend && uv run aperture-ally serve`).

## Layout

- `src/api/types.ts` — hand-written payload types; `src/api/client.ts` — typed fetch client (throws `ApiError` with the backend `detail`).
- `src/lib/` — pure logic: PTT key decisions (`ptt.ts`), region-drag normalization (`regions.ts`), event relevance + debounce + backoff (`events.ts`).
- `src/hooks/` — `usePushToTalk` (Space hold / Escape cancel), `useEventStream` (WebSocket with reconnect).
- The WebSocket is only a notification channel: relevant events trigger a debounced (150 ms)
  `GET /api/sessions/{sid}`; every (re)connect refetches everything.
- Keyboard PTT: hold Space while focus is not in a text field, select, or other control (buttons and
  checkboxes keep Space so keyboard users can still press them); the PTT button itself accepts Space.
  Escape cancels.

## E2E

`playwright.config.ts` starts its own backend via `webServer`:

```
npm run build && cd ../backend && APERTURE_ALLY_DATA_DIR=$(mktemp -d) APERTURE_ALLY_ASSESS_PROVIDER=mock \
  APERTURE_ALLY_SPEECH_PROVIDER=mock APERTURE_ALLY_RECORDER=mock APERTURE_ALLY_TRANSCRIBER=mock \
  APERTURE_ALLY_GLOBAL_KEYS=none APERTURE_ALLY_ALLOWED_ORIGINS='["http://127.0.0.1:8766",...]' \
  uv run aperture-ally serve --port 8766
```

The tests run against the real backend serving the freshly built UI on port 8766, with a fresh temp
data dir each run and no server reuse. Port 8766 must be free (`E2E_PORT` overrides it).

Browser: Playwright's own Chromium is used if it is installed (`npx playwright install chromium`). If it
is not (e.g. a sandbox with a different preinstalled build under `PLAYWRIGHT_BROWSERS_PATH`), the
config falls back to a `chromium-*` build found there. `PW_CHROMIUM_EXECUTABLE=/path/to/chrome`
forces a specific binary.

Tests:

- `coach-loop.spec.ts`: create simulated session → `basic_loop` replay → comparison "improved" → keeper accepted via confirm → coverage shows accepted (~25 s).
- `voice.spec.ts`: queue a mock transcript → hold the PTT button → listening → transcript and answer.
