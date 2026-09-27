# Aperture Ally (proof of concept)

A local-first macOS app that coaches a beginner through product photography **during the shoot**:

1. OM Capture (tethered E-M1 Mark II) writes a photo into a watch folder.
2. Aperture Ally ingests it for the **active shot requirement** (e.g. "Outsole"), preserves the original,
   builds an overview + full-resolution region crops + local measurements.
3. A vision model (OpenAI, Gemini or Claude, or the offline **mock** heuristic) returns structured, grounded coaching: a verdict
   per acceptance criterion and **one** physically achievable change, with explanation and trade-off.
4. The tip is **spoken** through your headphones. Hold a **push-to-talk** key (keyboard or Bluetooth
   remote) to interrupt and ask a follow-up.
5. The next photo is **compared** with the previous attempt and the advice ("improved / worse / mixed /
   uncertain"), and the experiment is recorded.
6. You explicitly accept a **keeper** for each required shot; the coverage report shows what is missing.

Starter shot lists: **running apparel** (8 shots: on-body hero, back, fabric close-up, fit profile, feature
details, label, flat lay, wear) and **running shoe** (6 shots). Both are fully editable per session.

The central question is whether this loop helps Drew make a visibly better photo within two or three
attempts *and* explain why. See [POC_STATUS.md](POC_STATUS.md) for what is implemented, simulated,
hardware-verified and model-evaluated — **those are different things**.

## Quick start (replay / mock — no camera, keys or microphone needed)

```bash
./scripts/dev.sh                      # uv sync, build UI once, serve http://127.0.0.1:8765
# in another terminal:
cd backend && uv run aperture-ally replay basic_loop
```

Open http://127.0.0.1:8765 and watch a simulated session: photos arrive via the real watch-folder path,
the mock coach speaks (simulated, logged in the UI), retakes are compared, keepers accepted. Replay
sessions and the mock provider are clearly labelled `SIMULATED` / `MOCK` in the UI and in exports.

Other scenarios: `ingest_stress` (partial writes, duplicates, late RAW, missing EXIF, EXIF rotation) and
`stale_switch` (switch shot while analysis is running; old advice must stay silent).

## Real shoot

Follow [docs/setup.md](docs/setup.md) (fresh Mac, ExifTool, OM Capture, API keys and model IDs,
headphones + microphone, PTT permissions and remote), then the manual gates in
[docs/hardware-checks.md](docs/hardware-checks.md).

## Commands

| Command | Purpose |
|---|---|
| `./scripts/dev.sh` | one-command launch (API + built UI on 127.0.0.1:8765) |
| `uv run aperture-ally doctor` | dependencies, arm64, providers (never prints keys), audio devices, permissions |
| `uv run aperture-ally preflight` | **before every shoot**: go/no-go on storage, watch folder, headphones, mic + transcription, PTT key, network, one real call per provider |
| `uv run aperture-ally inspect FILE…` | what the app reads from your camera files (identifying tags removed; safe to share) |
| `uv run aperture-ally replay <scenario>` | simulated camera against a running app |
| `uv run aperture-ally export [--session ID]` | coverage (JSON, Markdown, contact sheet), timing report and raw telemetry JSONL ([docs/telemetry.md](docs/telemetry.md)) |
| `uv run aperture-ally eval …` | offline evaluation, **session replay against other models/prompts**, live-trial summary ([evals/README.md](evals/README.md)) |
| `./scripts/check.sh` | lint + backend tests + frontend typecheck/unit/build/e2e (no paid calls) |
| `uv run pytest -m live` | **paid**: one real call per configured provider |

(`uv run …` commands run in `backend/`.)

## Layout

```
backend/aperture_ally/ api · domain · ingest · imaging · coaching · audio · input · persistence · telemetry
frontend/src/          React + TypeScript UI (Shoot, Coverage, Diagnostics, Sessions)
fixtures/manifest.json replay scenarios; synthetic images are generated into fixtures/generated/ (git-ignored)
evals/                 runner, rubric, dataset format; results/ is git-ignored
docs/                  setup · hardware-checks · architecture · telemetry · design-brief · poc-report
```

Private photos, recordings, credentials, the session database and paid-call outputs are git-ignored
by default. The service binds to loopback only.
