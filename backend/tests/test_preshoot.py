"""Pre-shoot features: received cue, voice feedback/commands, pause, spend cap, apparel, preflight, inspect."""

import asyncio
import json
from pathlib import Path

from aperture_ally.coaching.providers.mock import MockProvider
from aperture_ally.domain.models import Capture, Session
from aperture_ally.input.global_keys import KeySpec, PTTKeyTracker
from aperture_ally.preflight import GO, NO_GO, SKIP, WARN, Preflight

from .conftest import fast_settings


async def _done(h, s, n):
    items = [a for a in await h.app.store.assessments(s.id)
             if a.status in ("completed", "failed") and a.speech_status != "pending"]
    return items if len(items) >= n else None


async def _say(h, s, text):
    h.app.voice.transcriber.queue.append(text)
    await h.app.voice.press(s.id)
    await asyncio.sleep(0.3)
    await h.app.voice.release()
    await h.wait(lambda: _turn_finished(h, s, text), 10, f"voice turn '{text}'")


async def _turn_finished(h, s, text):
    turns = [t for t in await h.app.store.voice_turns(s.id) if t.transcript == text]
    return turns and turns[-1].status in ("spoken", "suppressed", "answered", "error")


async def test_received_and_failure_cues(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _done(h, s, 1), 10)
    assert h.app.cues.played.count("received") == 1
    h.mock.fail_mode = "unavailable"
    h.drop(s, fx / "P9260003.JPG")
    await h.wait(lambda: _done(h, s, 2), 10)
    assert h.app.cues.played == ["received", "received", "failure"]


async def test_spoken_received_cue_mode(make_harness, fx):
    h = await make_harness(received_cue="speech", auto_coach=False)
    s = await h.session()
    h.drop(s, fx / "P9260001.JPG")
    await h.wait(lambda: any(t == "Got 1." for t in h.speech.spoken), 10, "spoken cue")


async def test_voice_feedback_rates_and_records_lesson(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _done(h, s, 1), 10)
    await _say(h, s, "I moved the light camera left.")
    assert h.app.tracker.get(s.id).pending_change == "I moved the light camera left"
    h.drop(s, fx / "P9260003.JPG")
    await h.wait(lambda: _done(h, s, 2), 10)
    cap2 = (await h.captures(s))[-1]
    assert cap2.user_reported_change == "I moved the light camera left"
    await _say(h, s, "That helped.")
    await _say(h, s, "Lesson: side light shows the mesh without hotspots")
    (exp,) = await h.app.store.experiments(s.id)
    assert exp.follow_up_capture_id == cap2.id                     # rated the advice that was just tried
    assert exp.user_rating == "helpful" and "side light" in exp.lesson
    assert any(t.startswith("Marked helpful") for t in h.speech.spoken)


async def test_pause_and_resume_by_voice(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    await _say(h, s, "pause coaching")
    assert (await h.app.get_session(s.id)).coaching_paused
    h.drop(s, fx / "P9260002.JPG")
    await h.n_captures(s, 1)
    await h.settled()
    assert await h.app.store.assessments(s.id) == []               # photo kept, no paid call
    cap = (await h.captures(s))[0]
    await h.app.coaching.request_review(cap.id)                     # explicit review still allowed
    await h.wait(lambda: _done(h, s, 1), 10)
    await _say(h, s, "resume coaching")
    assert not (await h.app.get_session(s.id)).coaching_paused
    assert "Coaching paused. Photos are still saved." in h.speech.spoken


def test_pause_key_toggles():
    t = PTTKeyTracker(KeySpec.parse("f18"), None, "hold", KeySpec.parse("f17"))
    assert t.on_press("f17") == "pause_toggle" and t.on_press("f18") == "press"


class PaidLookingMock(MockProvider):
    name = "openai"
    model = "fake-paid-model"


async def test_session_budget_pauses_coaching_once(make_harness, fx):
    h = await make_harness(providers={"openai": PaidLookingMock(latency_s=0.05)}, session_max_model_calls=1)
    s = await h.session(assess_provider="openai")
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _done(h, s, 1), 10)
    h.drop(s, fx / "P9260003.JPG")
    items = await h.wait(lambda: _done(h, s, 2), 10)
    assert items[-1].status == "failed" and items[-1].error.startswith("Budget reached")
    sess = await h.app.get_session(s.id)
    assert sess.coaching_paused and sess.paused_reason.startswith("budget")
    await h.wait(lambda: any("budget is used up" in t for t in h.speech.spoken), 5, "budget notice")
    assert "failure" not in h.app.cues.played                        # budget stop isn't a fault
    h.drop(s, fx / "P9260001.JPG")                                    # further photos: no calls at all
    await h.n_captures(s, 3)
    await h.settled()
    assert len(await h.app.store.model_calls(s.id)) == 1
    assert sum("budget is used up" in t for t in h.speech.spoken) == 1    # announced once
    usage = await h.app.usage(s.id)
    assert usage["capped_calls"] == 1 and usage["exceeded"]
    # resuming while over budget stays paused; raising the cap then resuming works
    assert (await h.app.set_coaching_paused(s.id, False)).coaching_paused
    await h.app.update_session(s.id, {"max_model_calls": 10})
    assert not (await h.app.set_coaching_paused(s.id, False)).coaching_paused


async def test_mock_provider_never_counts_against_budget(make_harness, fx):
    h = await make_harness(session_max_model_calls=1)
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    h.drop(s, fx / "P9260003.JPG")
    items = await h.wait(lambda: _done(h, s, 2), 10)
    assert all(a.status == "completed" for a in items)


async def test_apparel_template_and_raw_exif(h, fx):
    s = await h.app.create_session(name="tee", template="running_apparel")
    titles = [x.title for x in await h.app.store.shots(s.id)]
    assert titles[0].startswith("Hero (on body") and "Label & materials tag" in titles and len(titles) == 8
    h.drop(s, fx / "P9260001.JPG")
    (cap,) = await h.n_captures(s, 1)
    cap = await h.app.store.get(Capture, cap.id)
    assert cap.exif_raw.get("Model") == "E-M1MarkII" and "_raw" not in cap.exif
    _ = Session


async def test_preflight_noninteractive_with_mocks(tmp_path, fx):
    s = fast_settings(tmp_path / "data", import_roots=[fx])
    out: list[str] = []
    pf = Preflight(s, interactive=False, providers=["mock"], out=out.append)
    report = await pf.run()
    by = {r["name"]: r for r in report["results"]}
    assert by["disk space"]["status"] in (GO, WARN)
    assert by["session / watch folder"]["status"] == WARN               # no session yet
    assert by["headphones (speech)"]["status"] == WARN                   # mock speech: nothing audible
    assert by["microphone"]["status"] == WARN
    assert by["push-to-talk key"]["status"] == WARN
    assert by["provider mock"]["status"] == GO and "valid result" in by["provider mock"]["detail"]
    assert report["verdict"] in (GO, NO_GO) and json.loads(Path(report["path"]).read_text())["results"]
    skip = Preflight(s, interactive=False, mic=False, keys=False, providers=[], out=out.append)
    rep2 = await skip.run()
    assert {r["name"]: r["status"] for r in rep2["results"]}["microphone"] == SKIP


def test_inspect_scrubs_identifying_tags(fx):
    from aperture_ally.photo_inspect import inspect_file, scrub

    assert scrub({"SerialNumber": "X", "GPSLatitude": 1, "Model": "E-M1"}) == {"Model": "E-M1"}
    r = inspect_file(fx / "P9260009.JPG")
    assert r["normalized"]["orientation"] == 6 and r["evidence"]["oriented_size"] == [2400, 1600]
    raw = inspect_file(fx / "P9260010.ORF")
    assert "error" in raw["raw"]                                        # fake RAW → reported, not crashed
