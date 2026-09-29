"""Speech through Aperture Ally.app (companion protocol), against a fake app on a loopback socket."""

import asyncio
import json

import pytest

from aperture_ally.audio.speech import CompanionSpeech


class FakeApp:
    """Speaks for `speak_s`, honours stop; records every request."""

    def __init__(self, speak_s=0.05, error=None, drop_after_start=False):
        self.speak_s, self.error, self.drop = speak_s, error, drop_after_start
        self.requests: list[dict] = []
        self.server = None
        self.stopped: asyncio.Event = asyncio.Event()

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def _client(self, reader, writer):
        playing: dict[str, asyncio.Task] = {}

        def send(obj):
            writer.write((json.dumps(obj) + "\n").encode())

        async def play(uid):
            send({"id": uid, "event": "started"})
            if self.drop:
                writer.close()
                return
            try:
                await asyncio.sleep(self.speak_s)
                send({"id": uid, "event": "error" if self.error else "done", "detail": self.error})
            except asyncio.CancelledError:
                send({"id": uid, "event": "cancelled", "detail": "stopped"})

        while line := await reader.readline():
            msg = json.loads(line)
            self.requests.append(msg)
            if msg["op"] == "speak":
                playing[msg["id"]] = asyncio.create_task(play(msg["id"]))
            elif msg["op"] == "stop" and msg.get("id") in playing:
                playing[msg["id"]].cancel()
                self.stopped.set()

    async def close(self):
        self.server.close()


async def test_speaks_through_the_app_with_rate_and_voice():
    app = FakeApp()
    s = CompanionSpeech(await app.start(), rate_wpm=270, voice="Samantha")
    started = []

    async def on_started():
        started.append(True)

    await s.speak("Needs retake.", on_started)
    assert started == [True] and not s.using_fallback
    assert app.requests[0] == {"op": "speak", "id": "u1", "text": "Needs retake.", "rate_wpm": 270, "voice": "Samantha"}
    await app.close()


async def test_interrupting_sends_stop_to_the_app():
    app = FakeApp(speak_s=5)
    s = CompanionSpeech(await app.start())

    async def noop():
        return None

    t = asyncio.create_task(s.speak("A long answer.", noop))
    await asyncio.sleep(0.1)
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    await asyncio.wait_for(app.stopped.wait(), 1)
    assert app.requests[-1] == {"op": "stop", "id": "u1"}
    await app.close()


async def test_app_not_running_falls_back_to_say():
    class Say:
        rate = voice = None
        spoken: list[str] = []

        async def speak(self, text, on_started):
            self.spoken.append(text)
            await on_started()

    say = Say()
    s = CompanionSpeech(1, rate_wpm=270, fallback=say)  # nothing listens on port 1

    async def noop():
        return None

    await s.speak("Hello.", noop)
    assert say.spoken == ["Hello."] and say.rate == 270 and s.using_fallback
    with pytest.raises(RuntimeError, match="isn't running"):
        await CompanionSpeech(1).speak("x", noop)


async def test_app_errors_and_disconnects_surface_instead_of_hanging():
    async def noop():
        return None

    app = FakeApp(error="speech engine not ready")
    with pytest.raises(RuntimeError, match="not ready"):
        await CompanionSpeech(await app.start()).speak("x", noop)
    await app.close()
    gone = FakeApp(drop_after_start=True)
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(CompanionSpeech(await gone.start()).speak("x", noop), 2)
    await gone.close()
