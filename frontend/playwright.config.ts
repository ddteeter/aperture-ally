import { defineConfig, devices } from "@playwright/test";
import { chromium } from "@playwright/test";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

/**
 * E2E runs against the real backend (mock provider/speech/recorder/transcriber, throwaway data dir)
 * which serves the freshly built frontend from frontend/dist on port 8766.
 */
const PORT = Number(process.env.E2E_PORT ?? 8766);
const BASE = `http://127.0.0.1:${PORT}`;

/**
 * Browser binary: PW_CHROMIUM_EXECUTABLE wins. Otherwise use Playwright's own browser if it is
 * installed (normal `npx playwright install` on a Mac); if not (e.g. a sandbox with a preinstalled,
 * differently-versioned build under PLAYWRIGHT_BROWSERS_PATH), fall back to any chromium found there.
 */
function chromiumExecutable(): string | undefined {
  if (process.env.PW_CHROMIUM_EXECUTABLE) return process.env.PW_CHROMIUM_EXECUTABLE;
  try {
    if (existsSync(chromium.executablePath())) return undefined;
  } catch {
    /* fall through */
  }
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH;
  if (!root || !existsSync(root)) return undefined;
  const dirs = readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort().reverse();
  for (const d of dirs) {
    for (const sub of ["chrome-linux64/chrome", "chrome-linux/chrome", "chrome-mac/Chromium.app/Contents/MacOS/Chromium"]) {
      const p = join(root, d, sub);
      if (existsSync(p)) return p;
    }
  }
  return undefined;
}

const executablePath = chromiumExecutable();

const backendEnv = [
  "PHOTO_COACH_DATA_DIR=$(mktemp -d)",
  "PHOTO_COACH_ASSESS_PROVIDER=mock",
  "PHOTO_COACH_SPEECH_PROVIDER=mock",
  "PHOTO_COACH_RECORDER=mock",
  "PHOTO_COACH_TRANSCRIBER=mock",
  "PHOTO_COACH_GLOBAL_KEYS=none",
  `PHOTO_COACH_ALLOWED_ORIGINS='["${BASE}","http://localhost:${PORT}"]'`,
].join(" ");

export default defineConfig({
  testDir: "./e2e",
  timeout: 150_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1, // one backend, one "active session" at a time
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: BASE,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1500, height: 1000 }, launchOptions: executablePath ? { executablePath } : {} },
    },
  ],
  webServer: {
    // Build the UI, then start the backend (which serves frontend/dist at / and /assets).
    command: `npm run build && cd ../backend && ${backendEnv} uv run photo-coach serve --port ${PORT}`,
    url: `${BASE}/api/health`,
    timeout: 180_000,
    reuseExistingServer: false,
    stdout: "pipe",
    stderr: "pipe",
  },
});
