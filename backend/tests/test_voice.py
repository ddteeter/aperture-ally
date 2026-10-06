"""PTT state machine, interruption, lost key-up, voice commands, key tracker."""

import asyncio
import time

from aperture_ally.audio.speech import MockSpeech
from aperture_ally.domain.models import AudioState
from aperture_ally.input.global_keys import KeySpec, PTTKeyTracker


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

    async def saved():  # the turn's status is stored just after speech finishes; under load that lags
        (t,) = await h.app.store.voice_turns(s.id)
        return t if t.status == "spoken" else None

    turn = await h.wait(saved, 10, "turn stored as spoken")
    assert turn.intent == "question" and turn.capture_id == r["capture_id"]
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


async def test_offline_question_gets_spoken_notice(h, fx):
    s = await h.session()
    await _coached(h, s, fx)
    h.mock.fail_mode = "unavailable"
    h.app.voice.transcriber.queue.append("why?")
    await h.app.voice.press(s.id)
    await asyncio.sleep(0.3)
    await h.app.voice.release()
    await h.wait(lambda: _spoken(h, 2), 10, "offline notice")
    assert "offline" in h.speech.spoken[-1]
    (turn,) = await h.app.store.voice_turns(s.id)
    assert turn.status == "error" and turn.error.startswith("AI unavailable")


async def test_empty_transcription_stays_empty():
    # The OpenAI SDK returns Transcription(text=''); '' used to fall back to the object's repr, which then went
    # to the coach as a question (found in preflight when nothing was said).
    from types import SimpleNamespace

    from aperture_ally.audio.recording import OpenAITranscriber

    t = OpenAITranscriber("sk-test", "gpt-transcribe")

    async def create(**_kw):
        return SimpleNamespace(text="", usage=None)

    t.client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    clip = SimpleNamespace(wav=b"RIFF")
    assert await t.transcribe(clip) == ""

    async def create_str(**_kw):
        return " hello "

    t.client.audio.transcriptions.create = create_str
    assert await t.transcribe(clip) == "hello"


def test_doctor_input_monitoring_only_needed_for_global_keys(tmp_path):
    import sys

    from aperture_ally.doctor import run_checks

    from .conftest import fast_settings

    if sys.platform != "darwin":
        return
    checks = {c["name"]: c for c in run_checks(fast_settings(tmp_path, global_keys="none"), quick=True)}
    assert checks["Input Monitoring permission"]["status"] == "ok"


def test_say_ends_with_silence_so_bluetooth_keeps_the_last_word():
    from aperture_ally.audio.speech import SaySpeech

    assert SaySpeech().text_for("Move the light left.") == "Move the light left. [[slnc 400]]"
    assert SaySpeech(tail_silence_ms=0).text_for("Move the light left.") == "Move the light left."


def test_doctor_warns_when_recording_from_the_headphones_mic():
    from aperture_ally.doctor import headset_mic_check

    bad = headset_mic_check("Drew’s AirPods Pro", "Drew’s AirPods Pro")
    assert bad["status"] == "warn" and "INPUT_DEVICE" in bad["fix"]
    assert headset_mic_check("MacBook Air Microphone", "Drew’s AirPods Pro")["status"] == "ok"


class _FakeStream:
    """Stands in for sounddevice.InputStream: the test pushes audio through the callback."""

    def __init__(self, callback, **_kw):
        self.callback = callback
        self.active = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        pass

    def feed(self, value: int, seconds: float):
        import numpy as np

        n = int(16000 * seconds)
        for i in range(0, n, 1600):  # 100 ms blocks, like a real callback
            self.callback(np.full((min(1600, n - i), 1), value, np.int16), 0, None, None)


def _continuous(**kw):
    from aperture_ally.audio.recording import ContinuousRecorder

    streams: list[_FakeStream] = []

    def factory(**k):
        streams.append(_FakeStream(**k))
        return streams[-1]

    return ContinuousRecorder(stream_factory=factory, **kw), streams


def test_always_open_mic_keeps_preroll_and_only_the_turn():
    rec, streams = _continuous(preroll_ms=300, ring_s=2.0)
    rec.open()
    s = streams[0]
    s.feed(100, 5.0)                     # before the press: only a bounded ring, nothing kept beyond ~2 s
    assert rec._ring_n <= 2.1 * 16000
    s.feed(200, 0.5)                     # the speaker starts a word just before pressing
    rec.start()
    s.feed(900, 1.0)
    clip = rec.stop()
    assert abs(clip.duration_s - 1.3) < 0.01          # 300 ms pre-roll + 1 s held
    s.feed(100, 1.0)                     # after release: not part of the clip
    rec.start()
    rec.abort()
    assert rec._clip is None


def test_always_open_mic_reopens_after_the_headphones_drop():
    rec, streams = _continuous()
    rec.open()
    streams[0].active = False            # AirPods back in the case: the stream dies
    assert not rec.is_open
    assert rec.ensure_open() and len(streams) == 2 and rec.reopened == 1


def test_always_open_mic_start_reports_why_the_mic_is_down():
    import pytest

    from aperture_ally.audio.recording import ContinuousRecorder

    def broken(**_k):
        raise RuntimeError("device unavailable")

    rec = ContinuousRecorder(stream_factory=broken)
    assert not rec.ensure_open() and "device unavailable" in rec.last_error
    with pytest.raises(RuntimeError):
        rec.start()


def test_doctor_accepts_the_headphones_mic_when_held_open():
    from aperture_ally.doctor import headset_mic_check

    assert headset_mic_check("Drew’s AirPods Pro", "Drew’s AirPods Pro", always_open=True)["status"] == "ok"


async def test_app_opens_the_always_open_mic_reports_it_and_closes_it(tmp_path):
    from aperture_ally.audio.recording import MockTranscriber
    from aperture_ally.audio.speech import MockSpeech
    from aperture_ally.services import ApertureAllyApp

    from .conftest import fast_settings

    rec, _streams = _continuous()
    app = ApertureAllyApp(fast_settings(tmp_path / "data"), speech=MockSpeech(), recorder=rec,
                          transcriber=MockTranscriber())
    await app.start()
    try:
        for _ in range(50):
            if rec.is_open:
                break
            await asyncio.sleep(0.02)
        assert rec.is_open
        assert any(e["type"] == "mic.status" and e["payload"]["open"] for e in app.bus.recent)
    finally:
        await app.stop()
    assert not rec.is_open


def test_always_open_mic_notices_a_stream_that_stops_delivering_and_reopens_it():
    # AirPods in the case: the stream can stay "active" while no audio (or only zeros) arrives.
    rec, streams = _continuous()
    now = [100.0]
    rec._clock = lambda: now[0]
    rec.open()
    streams[0].feed(50, 0.5)
    assert rec.stalled() is None and rec.status()["level"] == 50.0
    now[0] += 2.0                                   # no callbacks for 2 s
    assert rec.stalled().startswith("no audio")
    assert rec.ensure_open() and len(streams) == 2 and rec.reopened == 1
    assert rec.last_stall.startswith("no audio") and rec.last_error is None
    streams[1].feed(0, 0.2)                          # callbacks, but pure zeros
    now[0] += 3.5
    streams[1].feed(0, 0.2)
    assert rec.stalled().startswith("silent")


def test_always_open_mic_falls_back_while_the_headphones_are_away_and_switches_back():
    from aperture_ally.audio.recording import ContinuousRecorder

    present = ["AirPods", "MacBook Air Microphone"]
    refreshes = []
    streams: list[_FakeStream] = []

    def factory(**k):
        s = _FakeStream(**k)
        s.device = k["device"]
        streams.append(s)
        return s

    now = [0.0]
    rec = ContinuousRecorder("AirPods", stream_factory=factory, list_inputs=lambda: list(present),
                             refresh_devices=lambda: refreshes.append(1))
    rec._clock = lambda: now[0]
    rec.open()
    assert streams[-1].device == "AirPods" and not rec.fallback
    present.remove("AirPods")                 # into the case: the stream dies
    streams[-1].active = False
    assert rec.ensure_open() and streams[-1].device is None and rec.fallback   # system default meanwhile
    assert rec.status()["active_device"] == "system default"
    present.insert(0, "AirPods")              # back in the ears
    now[0] += 1.0
    rec.ensure_open()
    assert streams[-1].device is None         # not re-checked yet (every 5 s)
    now[0] += 5.0
    assert rec.ensure_open() and streams[-1].device == "AirPods" and not rec.fallback
    assert len(refreshes) == len(streams)     # the device list is re-read before every open


def test_fallback_rechecks_are_not_counted_as_reopens():
    from aperture_ally.audio.recording import ContinuousRecorder

    streams: list[_FakeStream] = []
    now = [0.0]
    rec = ContinuousRecorder("AirPods", stream_factory=lambda **k: streams.append(_FakeStream(**k)) or streams[-1],
                             list_inputs=lambda: ["MacBook Air Microphone"], refresh_devices=lambda: None)
    rec._clock = lambda: now[0]
    rec.open()
    for _ in range(3):
        now[0] += 6.0
        streams[-1].feed(10, 0.1)
        rec.ensure_open()
    assert rec.fallback and len(streams) == 4 and rec.reopened == 0


def test_f_numbers_are_read_without_the_slash():
    from aperture_ally.audio.speech import for_speech

    assert for_speech("Stop down to f/4, then f/5.6 or ƒ/ 8.") == "Stop down to f 4, then f 5.6 or f 8."
    assert for_speech("Shutter 1/60 and/or ISO 400") == "Shutter 1/60 and/or ISO 400"
