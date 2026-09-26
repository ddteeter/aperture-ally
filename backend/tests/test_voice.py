"""PTT state machine, interruption, lost key-up, voice commands, key tracker."""

import asyncio
import time

from photo_coach.audio.speech import MockSpeech
from photo_coach.domain.models import AudioState
from photo_coach.input.global_keys import KeySpec, PTTKeyTracker


async def _coached(h, s, fx):
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _spoken(h, 1), 10, "advice spoken")


async def _spoken(h, n):
    return len(h.speech.spoken) >= n


async def _idle(h):
    return h.app.voice.state == AudioState.idle


async def test_press_release_question_answered_and_spoken(h, fx):
    s = await h.session()
    await _coached(h, s, fx)
    h.app.voice.transcriber.queue.append("Why does the glare matter here?")
    r = await h.app.voice.press(s.id)
    assert h.app.voice.state == AudioState.listening and r["capture_id"]
    await asyncio.sleep(0.3)
    await h.app.voice.release()
    await h.wait(lambda: _spoken(h, 2), 10, "answer spoken")
    (turn,) = await h.app.store.voice_turns(s.id)
    assert turn.intent == "question" and turn.status == "spoken" and turn.capture_id == r["capture_id"]
    assert "Why does the glare matter" in turn.answer


async def test_key_repeat_ignored_and_single_recording(h, fx):
    s = await h.session()
    await h.app.voice.press(s.id)
    for _ in range(10):
        r = await h.app.voice.press(s.id)
        assert r == {"ignored": "already listening"}
    assert h.app.voice.repeats_ignored == 10
    await h.app.voice.cancel()
    assert len(await h.app.store.voice_turns(s.id)) == 1


async def test_empty_clip_makes_no_api_call(h, fx):
    s = await h.session()
    t = h.app.voice.transcriber
    t.queue.append("should not be used")
    await h.app.voice.press(s.id)
    await h.app.voice.release()  # ~0 s hold
    (turn,) = await h.app.store.voice_turns(s.id)
    assert turn.status == "empty" and list(t.queue) == ["should not be used"]
    assert h.app.voice.state == AudioState.idle


async def test_lost_key_up_times_out_and_discards(make_harness):
    h = await make_harness(ptt_max_seconds=0.4)
    s = await h.session()
    await h.app.voice.press(s.id)
    await asyncio.sleep(0.8)
    assert h.app.voice.state == AudioState.idle and not h.app.voice.recorder.active
    (turn,) = await h.app.store.voice_turns(s.id)
    assert turn.status == "timed_out"
    assert (await h.app.voice.release()) == {"ignored": "not listening"}


async def test_ptt_interrupts_speech_quickly(make_harness, fx):
    h = await make_harness(speech=MockSpeech(words_per_s=2))  # slow speech: ~10 s of talking
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: h.app.audio.speaking, 10, "speaking")
    t0 = time.monotonic()
    await h.app.voice.press(s.id)
    assert not h.app.audio.speaking
    assert (time.monotonic() - t0) < 0.3
    assert h.speech.cancelled and h.app.voice.state == AudioState.listening
    await h.app.voice.cancel()


async def test_cancel_stops_speech_and_answer(make_harness, fx):
    h = await make_harness(speech=MockSpeech(words_per_s=2))
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: h.app.audio.speaking, 10, "speaking")
    res = await h.app.voice.cancel()
    assert "speech" in res["cancelled"] and not h.app.audio.speaking


async def test_new_press_supersedes_pending_answer(h, fx):
    s = await h.session()
    await _coached(h, s, fx)
    h.mock.latency_s = 0.6
    h.app.voice.transcriber.queue.extend(["first question?", "second question?"])
    await h.app.voice.press(s.id)
    await asyncio.sleep(0.3)
    await h.app.voice.release()
    await asyncio.sleep(0.1)
    await h.app.voice.press(s.id)   # interrupts: first answer must never be spoken
    await asyncio.sleep(0.3)
    await h.app.voice.release()
    await h.wait(lambda: _idle(h), 10)
    await h.wait(lambda: _spoken(h, 2), 10)
    turns = await h.app.store.voice_turns(s.id)
    assert turns[0].status in ("cancelled", "suppressed") and turns[1].status == "spoken"
    assert "second question" in h.speech.spoken[-1] or len(h.speech.spoken) == 2


async def test_voice_accept_requires_unambiguous_phrase(h, fx):
    s = await h.session()
    await _coached(h, s, fx)
    upper = await h.shot(s, "Upper")
    h.app.voice.transcriber.queue.append("accept")          # ambiguous → treated as a question
    await h.app.voice.press(s.id)
    await asyncio.sleep(0.3)
    await h.app.voice.release()
    await h.wait(lambda: _idle(h), 10)
    assert await h.app.store.active_keeper(upper.id) is None
    h.app.voice.transcriber.queue.append("Accept this photo as keeper.")
    r = await h.app.voice.press(s.id)
    await asyncio.sleep(0.3)
    await h.app.voice.release()
    await h.wait(lambda: h.app.store.active_keeper(upper.id), 10, "keeper")
    k = await h.app.store.active_keeper(upper.id)
    assert k.capture_id == r["capture_id"] and k.source == "voice"


async def test_repeat_and_next_shot_commands(h, fx):
    s = await h.session()
    await _coached(h, s, fx)
    advice = h.speech.spoken[-1]
    h.app.voice.transcriber.queue.extend(["repeat that", "next shot"])
    for _ in range(2):
        await h.app.voice.press(s.id)
        await asyncio.sleep(0.3)
        await h.app.voice.release()
        await h.wait(lambda: _idle(h), 10)
    assert h.speech.spoken[-2] == advice
    active = (await h.app.get_session(s.id)).active_shot_id
    assert active != (await h.shot(s, "Upper")).id and "Next shot" in h.speech.spoken[-1]


async def test_question_about_older_photo_is_identified(h, fx):
    s = await h.session()
    await _coached(h, s, fx)
    first = (await h.captures(s))[0]
    h.drop(s, fx / "P9260003.JPG")
    await h.wait(lambda: _spoken(h, 2), 10)
    h.app.voice.transcriber.queue.append("why was that?")
    await h.app.voice.press(s.id, capture_id=first.id)
    await asyncio.sleep(0.3)
    await h.app.voice.release()
    await h.wait(lambda: _spoken(h, 3), 10)
    assert "earlier" in h.speech.spoken[-1].lower()


async def test_mic_failure_fails_closed(h):
    s = await h.session()

    def boom():
        raise OSError("no input device")

    h.app.voice.recorder.start = boom
    r = await h.app.voice.press(s.id)
    assert "error" in r and h.app.voice.state == AudioState.idle
    (turn,) = await h.app.store.voice_turns(s.id)
    assert turn.status == "error"


def test_key_tracker_hold_repeat_release():
    t = PTTKeyTracker(KeySpec.parse("f18"), KeySpec.parse("escape"), "hold")
    assert t.on_press("f18", 0.0) == "press"
    assert t.on_press("f18", 0.05) is None and t.on_press("f18", 0.10) is None  # OS auto-repeat
    assert t.on_press("a", 0.2) is None                                        # unrelated keys ignored
    assert t.on_release("f18", 1.0) == "release"
    assert t.on_release("f18", 1.1) is None                                    # stray release
    kinds = [e["kind"] for e in t.log]
    assert kinds == ["press", "repeat", "repeat", "release"]
    assert t.log[-1]["hold_ms"] == 1000.0
    assert all(e["key"] in ("f18", "escape") for e in t.log)                  # nothing else logged
    assert t.on_press("escape", 2.0) == "cancel"


def test_key_tracker_chord_toggle_and_learn():
    t = PTTKeyTracker(KeySpec.parse("ctrl+page_down"), None, "toggle")
    assert t.on_press("page_down") is None            # modifier not held
    t.on_press("ctrl_l")
    assert t.on_press("page_down") == "toggle"
    assert t.on_release("page_down") is None          # toggle ignores release
    t.on_release("ctrl_l")
    t.learn_waiting = True
    assert t.on_press("shift") is None and t.learn_waiting
    assert t.on_press("f13") == "learned" and t.learned == "shift+f13"
