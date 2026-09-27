"""Pre-shoot go / no-go check: `aperture-ally preflight`.

Walks through everything that must work at the camera, in the order you'd discover it failing:
dependencies → storage and watch folder → headphones (cue + speech) → microphone + transcription →
push-to-talk key → network → one real assessment per configured provider. Interactive steps ask you to
confirm what you heard; ``--yes`` skips confirmations (they are then reported as unconfirmed warnings).
Writes a JSON record under ``<data dir>/preflight/``. Run it with the app stopped (it uses the mic/keys).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .domain.models import SessionStatus, utcnow
from .term import status_line, use_color, verdict_line

GO, WARN, NO_GO, SKIP = "go", "warn", "no_go", "skipped"
MIN_FREE_GB, WARN_FREE_GB = 1.0, 5.0


class Preflight:
    def __init__(self, settings: Settings, *, interactive: bool = True, paid: bool = True, mic: bool = True,
                 keys: bool = True, session_prefix: str | None = None, providers: list[str] | None = None,
                 ask: Callable[[str], str] = input, out: Callable[[str], None] = print):
        self.s = settings
        self.interactive, self.paid, self.mic, self.keys = interactive, paid, mic, keys
        self.session_prefix = session_prefix
        self.providers_override = providers
        self.ask, self.out = ask, out
        # Colour only when writing to a real terminal through print (tests pass their own `out`).
        self.color = out is print and use_color()
        self.results: list[dict[str, Any]] = []

    def add(self, name: str, status: str, detail: str = "", **data: Any) -> None:
        self.results.append({"name": name, "status": status, "detail": detail, **data})
        level = {GO: "ok", WARN: "warn", NO_GO: "fail", SKIP: "skip"}[status]
        self.out(status_line(level, name, detail, color=self.color))

    def confirm(self, question: str) -> bool | None:
        if not self.interactive:
            return None
        return self.ask(f"   ? {question} [y/n] ").strip().lower().startswith("y")

    # --- steps ---------------------------------------------------------------------------
    def check_doctor(self) -> None:
        from .doctor import run_checks

        checks = run_checks(self.s)
        fails = [c for c in checks if c["status"] == "fail"]
        warns = [c for c in checks if c["status"] == "warn"]
        if fails:
            self.add("doctor", NO_GO, "; ".join(f"{c['name']} ({c['fix'] or c['detail']})" for c in fails))
        else:
            self.add("doctor", WARN if warns else GO,
                     f"{len(checks) - len(warns)} ok, {len(warns)} warnings: " + ", ".join(c["name"] for c in warns))

    def check_storage(self) -> None:
        from .persistence.db import Store

        self.s.data_dir.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.s.data_dir).free / 1e9
        status = NO_GO if free < MIN_FREE_GB else WARN if free < WARN_FREE_GB else GO
        self.add("disk space", status, f"{free:.1f} GB free at {self.s.data_dir}", free_gb=round(free, 1))
        store = Store(self.s.db_path)
        try:
            sessions = store.list_sessions()
            if self.session_prefix:
                sessions = [x for x in sessions if x.id.startswith(self.session_prefix)]
            else:
                sessions = [x for x in sessions if x.status == SessionStatus.active]
        finally:
            store.close()
        if not sessions:
            self.add("session / watch folder", WARN, "no active session yet: create one (Sessions tab) and point its "
                     "watch folder at OM Capture's save folder")
            return
        sess = sessions[0]
        folder = Path(sess.watch_folder or "")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".aperture-ally-preflight"  # dot-files are ignored by ingestion
            probe.write_text("ok")
            probe.unlink()
            wfree = shutil.disk_usage(folder).free / 1e9
            self.add("session / watch folder", GO, f"'{sess.name}' watches {folder} ({wfree:.1f} GB free); "
                     f"provider {sess.assess_provider}{' — MOCK' if sess.assess_provider == 'mock' else ''}",
                     session_id=sess.id)
            if sess.assess_provider == "mock":
                self.add("session provider", WARN, "active session uses the mock provider (not real coaching)")
        except OSError as exc:
            self.add("session / watch folder", NO_GO, f"{folder}: {exc}")

    async def check_audio_out(self) -> None:
        from .services import build_cues, build_speech

        speech, cues = build_speech(self.s), build_cues(self.s)
        if speech.name != "say":
            self.add("headphones (speech)", WARN, f"speech provider is '{speech.name}', nothing audible")
            return
        self.out("   … playing the photo-received sound, then a sentence")
        cues.play("received")
        await asyncio.sleep(0.8)
        t0 = time.monotonic()
        started: list[float] = []

        async def on_started() -> None:
            started.append(time.monotonic() - t0)

        try:
            await speech.speak("Aperture Ally preflight. If you can hear this in your headphones, answer yes.", on_started)
        except Exception as exc:
            self.add("headphones (speech)", NO_GO, f"speech failed: {exc}")
            return
        heard = self.confirm("Did you hear the sound AND the sentence in your headphones (not the laptop speakers)?")
        detail = f"say started in {started[0] * 1000:.0f} ms" if started else ""
        if heard is None:
            self.add("headphones (speech)", WARN, detail + " (not confirmed: --yes)")
        else:
            self.add("headphones (speech)", GO if heard else NO_GO,
                     detail + ("" if heard else " — check macOS output device / APERTURE_ALLY_SAY_AUDIO_DEVICE"))

    async def check_mic(self) -> None:
        from .services import build_recorder, build_transcriber

        if not self.mic:
            self.add("microphone", SKIP, "--skip-mic")
            return
        rec = build_recorder(self.s)
        if rec.name == "mock":
            self.add("microphone", WARN, "recorder is 'mock' (APERTURE_ALLY_RECORDER=sounddevice for the real mic)")
            return
        self.out("   … say “testing one two three” now (3 seconds)")
        try:
            rec.start()
            await asyncio.sleep(3.0)
            clip = rec.stop()
        except Exception as exc:
            self.add("microphone", NO_GO, f"{exc} — grant Microphone permission to your terminal")
            return
        if clip.is_empty(self.s.min_utterance_s):
            self.add("microphone", NO_GO, f"too quiet (rms {clip.rms:.0f}); check input device {self.s.input_device or 'default'}")
            return
        self.add("microphone", GO, f"{clip.duration_s:.1f} s, rms {clip.rms:.0f}")
        tr = build_transcriber(self.s)
        if tr.name != "mock" and not self.paid:
            self.add("transcription", SKIP, "--no-paid")
            return
        t0 = time.monotonic()
        try:
            text = await tr.transcribe(clip)
        except Exception as exc:
            self.add("transcription", NO_GO, str(exc))
            return
        ok = self.confirm(f'Transcript: "{text}" — is that right?')
        self.add("transcription", WARN if ok is None or tr.name == "mock" else GO if ok else WARN,
                 f"{tr.name}: “{text}” in {(time.monotonic() - t0) * 1000:.0f} ms"
                 + (" (mock transcriber)" if tr.name == "mock" else ""))

    async def check_keys(self) -> None:
        if not self.keys:
            self.add("push-to-talk key", SKIP, "--skip-keys")
            return
        if self.s.global_keys != "pynput":
            self.add("push-to-talk key", WARN, "global keys off: only the on-screen button / Space work "
                     "(APERTURE_ALLY_GLOBAL_KEYS=pynput for the remote)")
            return
        from .input.global_keys import GlobalKeyListener

        actions: list[str] = []
        want = {"press", "release"} if self.s.ptt_mode == "hold" else {"toggle"}
        done = asyncio.Event()

        async def dispatch(a: str) -> None:
            actions.append(a)
            if want <= set(actions):
                done.set()

        async def failed(err: str) -> None:
            actions.append(f"failure:{err}")

        listener = GlobalKeyListener(self.s.ptt_key, self.s.cancel_key, self.s.ptt_mode, dispatch, failed,
                                     self.s.pause_key)
        listener.start(asyncio.get_running_loop())
        if listener.error:
            self.add("push-to-talk key", NO_GO, listener.error)
            return
        self.out(f"   … press and HOLD the push-to-talk key ({self.s.ptt_key}) for ~2 s, then release (20 s timeout)")
        try:
            await asyncio.wait_for(done.wait(), 20)
        except TimeoutError:
            pass
        listener.stop()
        log = listener.tracker.log
        holds = [e.get("hold_ms") for e in log if e["kind"] == "release"]
        repeats = sum(1 for e in log if e["kind"] == "repeat")
        if want <= set(actions):
            self.add("push-to-talk key", GO, f"{self.s.ptt_key}: events {[e['kind'] for e in log][:6]}"
                     + (f", hold {holds[-1]:.0f} ms" if holds else "") + f", {repeats} auto-repeats ignored")
        else:
            self.add("push-to-talk key", NO_GO, f"saw {actions or 'nothing'} — grant Input Monitoring to your terminal, "
                     "or find the remote's key with Diagnostics → Learn key")

    async def check_network(self) -> None:
        from .telemetry.recorder import PROVIDER_HOSTS, probe_host

        hosts = [PROVIDER_HOSTS[p] for p in self._providers() if p in PROVIDER_HOSTS]
        if not hosts:
            self.add("network", SKIP, "no real provider configured")
            return
        for h in hosts:
            r = await probe_host(h)
            self.add(f"network → {h}", GO if r["ok"] else NO_GO,
                     f"DNS {r.get('dns_ms')} ms, TCP {r.get('tcp_connect_ms')} ms" if r["ok"] else r.get("error", ""))

    def _providers(self) -> list[str]:
        if self.providers_override is not None:
            return self.providers_override
        from .coaching.service import ProviderRegistry

        return [p for p, ok in ProviderRegistry(self.s).configured().items() if ok and p != "mock"]

    async def check_providers(self) -> None:
        providers = self._providers()
        if not providers:
            self.add("coaching providers", WARN, "no real provider configured (only mock)")
            return
        if not self.paid and any(p != "mock" for p in providers):
            self.add("coaching providers", SKIP, "--no-paid")
            return
        from .fixtures_gen import REGIONS, generate
        from .services import ApertureAllyApp

        tmp = Path(tempfile.mkdtemp(prefix="aperture-ally-preflight-"))
        fx = tmp / "fx"
        generate(fx)
        s = self.s.model_copy(update={"data_dir": tmp / "data", "speech_provider": "none", "recorder": "mock",
                                      "transcriber": "mock", "global_keys": "none", "auto_coach": False,
                                      "log_to_file": False, "network_probe_interval_s": 0,
                                      "import_roots": [fx], "stability_interval_ms": 20})
        app = ApertureAllyApp(s)
        await app.start(watch=False)
        try:
            sess = await app.create_session(name="preflight", template="running_shoe", assess_provider="mock")
            shot = next(x for x in await app.store.shots(sess.id) if x.title.startswith("Upper"))
            await app.update_shot(shot.id, {"sharp_regions": [REGIONS["mesh"]]})
            (cid,) = await app.ingest.import_paths(sess.id, [fx / "P9260002.JPG"], shot_id=shot.id)
            await app.ingest.drain()
            for p in providers:
                t0 = time.monotonic()
                a = await app.coaching.run_assessment(cid, trigger="eval", provider_name=p, speak=False, kind="assess")
                secs = time.monotonic() - t0
                if a and a.status == "completed":
                    self.add(f"provider {p}", GO if secs < 15 else WARN,
                             f"{a.model_resolved}: valid result in {secs:.1f} s"
                             + (" (after one repair)" if a.repair_attempted else "")
                             + f", tokens in/out {a.usage.get('input_tokens')}/{a.usage.get('output_tokens')}"
                             + (" — slow for live coaching" if secs >= 15 else ""),
                             latency_s=round(secs, 2), model=a.model_resolved)
                else:
                    self.add(f"provider {p}", NO_GO, (a.error if a else "no result") or "failed")
        finally:
            await app.stop()
            shutil.rmtree(tmp, ignore_errors=True)

    # --- run -----------------------------------------------------------------------------
    async def run(self) -> dict[str, Any]:
        self.out("Aperture Ally preflight\n")
        self.check_doctor()
        self.check_storage()
        await self.check_audio_out()
        await self.check_mic()
        await self.check_keys()
        await self.check_network()
        await self.check_providers()
        self.out("   (manual) OM Capture: camera connected in tether mode, saving to the session's watch folder")
        verdict = NO_GO if any(r["status"] == NO_GO for r in self.results) else GO
        report = {"at": utcnow(), "verdict": verdict, "results": self.results}
        out_dir = self.s.data_dir / "preflight"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"preflight-{time.strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps(report, indent=2, default=str))
        warns = sum(1 for r in self.results if r["status"] == WARN)
        head = "GO" if verdict == GO else "NO-GO"
        level = "fail" if verdict == NO_GO else "warn" if warns else "ok"
        self.out(f"\n{verdict_line(f'{head} — {warns} warning(s).', level, color=self.color)} Saved {path}")
        report["path"] = str(path)
        return report
