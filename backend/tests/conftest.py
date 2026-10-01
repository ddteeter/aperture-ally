from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from aperture_ally.audio.recording import MockRecorder, MockTranscriber
from aperture_ally.audio.speech import MockSpeech
from aperture_ally.coaching.providers.mock import MockProvider
from aperture_ally.config import Settings
from aperture_ally.fixtures_gen import REGIONS, generate
from aperture_ally.services import ApertureAllyApp


@pytest.fixture(scope="session")
def fx(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("fixtures")
    generate(d)
    return d


def fast_settings(data_dir: Path, **kw) -> Settings:
    base = dict(
        data_dir=data_dir, speech_provider="mock", recorder="mock", transcriber="mock",
        stability_interval_ms=40, stability_checks=3, stability_timeout_s=3.0, reconcile_interval_s=0.3,
        pair_grace_s=0.8, raw_unverified_settle_s=0.3, attribution_ambiguity_s=0.5, teaching_prompt_every=0,
        import_roots=[data_dir.parent], ptt_max_seconds=5, min_utterance_s=0.2, ready_cue=False, _env_file=None,
        power_sample_s=0,
    )
    base.update(kw)
    return Settings(**base)


class Harness:
    def __init__(self, app: ApertureAllyApp):
        self.app = app
        self.speech: MockSpeech = app.speech  # type: ignore[assignment]
        self.mock: MockProvider = app.providers.get("mock")  # type: ignore[assignment]

    async def session(self, setup: dict | None = None, **kw):
        return await self.app.create_session(name="test", product="shoe", setup=setup or {
            "support": "tripod", "light": "continuous", "light_mobility": "movable",
            "subject_movement": "stationary", "exposure_mode": "manual", "iso_mode": "manual"}, **kw)

    async def shot(self, session, title_prefix: str):
        return next(s for s in await self.app.store.shots(session.id) if s.title.startswith(title_prefix))

    async def use_shot(self, session, title_prefix: str, region: str | None = None):
        shot = await self.shot(session, title_prefix)
        if region:
            shot = await self.app.update_shot(shot.id, {"sharp_regions": [REGIONS[region]]})
        await self.app.set_active_shot(session.id, shot.id)
        return shot

    def drop(self, session, src: Path, name: str | None = None) -> Path:
        dest = Path(session.watch_folder) / (name or src.name)
        dest.write_bytes(src.read_bytes())
        return dest

    async def wait(self, pred: Callable, timeout: float = 10.0, what: str = "condition"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            res = pred()
            if asyncio.iscoroutine(res):
                res = await res
            if res:
                return res
            await asyncio.sleep(0.05)
        raise AssertionError(f"timed out waiting for {what}")

    async def captures(self, session):
        return await self.app.store.captures(session.id)

    async def n_captures(self, session, n: int, timeout: float = 10.0):
        async def ok():
            caps = await self.captures(session)
            return caps if len(caps) >= n and all(c.evidence for c in caps) else None
        return await self.wait(ok, timeout, f"{n} captures")

    async def settled(self, timeout: float = 10.0):
        await self.app.ingest.drain(timeout)
        await self.app.coaching.drain(timeout)


@pytest.fixture
async def make_harness(tmp_path):
    apps: list[ApertureAllyApp] = []

    async def make(**kw) -> Harness:
        data = kw.pop("data_dir", tmp_path / "data")
        providers = kw.pop("providers", None)
        speech = kw.pop("speech", None) or MockSpeech(words_per_s=400)
        app = ApertureAllyApp(fast_settings(data, **kw), providers=providers, speech=speech,
                            recorder=MockRecorder(), transcriber=MockTranscriber())
        await app.start()
        apps.append(app)
        return Harness(app)

    yield make
    for a in apps:
        try:
            await a.stop()
        except Exception:
            pass


@pytest.fixture
async def h(make_harness) -> Harness:
    return await make_harness()
