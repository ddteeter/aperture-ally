"""Direct camera control against a simulated E-M1 II (camera/driver.py FakeDriver): no hardware needed."""

import asyncio
import time

import pytest

from aperture_ally.camera import settings as S
from aperture_ally.camera.driver import FakeDriver, parse_unknown
from aperture_ally.camera.service import CameraService, NotConnected


def test_settings_order_step_display_and_speech():
    assert S.ordered("iso", ["200", "Auto", "100", "LOW"]) == ["Auto", "100", "200"]
    assert S.ordered("aperture", ["8.0", "1.8", "2.8"]) == ["1.8", "2.8", "8.0"]
    order = S.ordered("aperture", ["1.8", "2.0", "2.2", "2.5", "2.8"])
    assert S.step("2.8", order, -1) == ("2.5", False)
    assert S.step("1.8", order, -1) == ("1.8", True)
    assert S.index_of("8", ["5.6", "8.0"]) == 1
    assert S.display("aperture", "2.8") == "f/2.8" and S.display("aperture", "8.0") == "f/8"
    assert S.display("exposurecompensation", "0.7") == "+⅔"
    assert S.display("exposurecompensation", "-1.3") == "−1⅓"
    assert S.display("exposurecompensation", "0.0") == "±0.0"
    assert S.display("iso", "Auto") == "ISO Auto" and S.display("iso", "200") == "ISO 200"
    assert S.spoken("aperture", "2.8") == "f 2.8"
    assert S.spoken("aperture", "1.8", end=S.end_word("aperture", -1)) == "f 1.8, widest"
    assert S.spoken("exposurecompensation", "0.7") == "plus two thirds"
    assert S.spoken("exposurecompensation", "-1.3") == "minus 1 and a third"
    assert S.spoken("exposurecompensation", "0") == "compensation zero"
    assert S.spoken("iso", "Auto") == "ISO auto"


def test_vendor_events_are_parsed():
    ev = parse_unknown("PTP Event c101, Param1 00000000")
    assert ev.kind == "ptp" and ev.code == 0xC101
    ev = parse_unknown("PTP Property d01c changed, \"...\"")
    assert ev.kind == "prop" and ev.prop == "d01c"


class Harness:
    def __init__(self, tmp_path, fake: FakeDriver | None = None):
        self.fake = fake or FakeDriver()
        self.events: list[tuple[str, dict]] = []
        self.svc = CameraService("mock", lambda: self.fake, lambda t, **p: self.events.append((t, p)),
                                 inbox=tmp_path / "inbox", poll_s=0.05)
        self.svc.destination = tmp_path / "shoot"

    async def wait(self, pred, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return
            await asyncio.sleep(0.02)
        raise AssertionError(f"timed out; state={self.svc.state} events={self.events[-5:]}")

    def types(self):
        return [t for t, _ in self.events]


@pytest.fixture
def cam(tmp_path):
    h = Harness(tmp_path)
    yield h
    h.svc.stop()


async def test_connects_reads_settings_and_steps_to_the_lens_limit(cam):
    cam.svc.start()
    await cam.wait(lambda: cam.svc.state == "connected")
    assert cam.svc.values["aperture"] == "5.6" and cam.svc.orders["iso"][0] == "Auto"
    r = await cam.svc.step("aperture", -1)
    assert r["value"] == "5.0" and r["display"] == "f/5" and r["end"] is None and r["spoken"] == "f 5"
    cam.fake.values["aperture"] = "2.0"
    cam.svc.values["aperture"] = "2.0"
    r = await cam.svc.step("aperture", -1)  # f/1.8 exists and the lens allows it
    assert r["value"] == "1.8" and r["end"] is None
    r = await cam.svc.step("aperture", -1)  # f/1.6: the body offers it, the f/1.8 lens clamps it back
    assert r["value"] == "1.8" and r["end"] == "widest" and r["spoken"] == "f 1.8, widest"
    r = await cam.svc.step("iso", -1)
    assert r["value"] == "Auto" and r["end"] == "lowest"
    r = await cam.svc.step("exposurecompensation", 1)
    assert r["display"] == "+⅓"
    assert ("camera.setting", r) in cam.events


async def test_a_photo_lands_in_the_shoot_folder_with_its_raw_under_one_stem(cam, tmp_path):
    cam.svc.start()
    await cam.wait(lambda: cam.svc.state == "connected")
    r = await cam.svc.trigger()
    assert r["first_photo"] is True
    await cam.wait(lambda: "camera.photo.raw" in cam.types())
    names = sorted(p.name for p in (tmp_path / "shoot").iterdir())
    assert names == ["AA9290001.JPG", "AA9290001.ORF"]
    photo = next(p for t, p in cam.events if t == "camera.photo")
    assert photo["first_of_connection"] is True and photo["name"] == "AA9290001.JPG"
    assert "camera.shutter" in cam.types()
    await cam.svc.trigger()
    await cam.wait(lambda: len([t for t in cam.types() if t == "camera.photo"]) == 2)
    assert cam.svc.first_photo is False and cam.svc.photos == 2


async def test_existing_names_are_not_overwritten(cam, tmp_path):
    (tmp_path / "shoot").mkdir()
    (tmp_path / "shoot" / "AA9290001.JPG").write_bytes(b"older")
    cam.svc.start()
    await cam.wait(lambda: cam.svc.state == "connected")
    await cam.svc.trigger()
    await cam.wait(lambda: "camera.photo.raw" in cam.types())
    assert (tmp_path / "shoot" / "AA9290001.JPG").read_bytes() == b"older"
    assert {p.name for p in (tmp_path / "shoot").iterdir()} >= {"AA9290001-2.JPG", "AA9290001-2.ORF"}


async def test_disconnect_goes_to_asleep_and_reconnects_when_the_camera_is_back(cam):
    cam.svc.start()
    await cam.wait(lambda: cam.svc.state == "connected")
    cam.fake.present = False
    await cam.wait(lambda: cam.svc.state == "asleep")
    with pytest.raises(NotConnected):
        await cam.svc.step("aperture", 1)
    cam.fake.present = True
    await cam.wait(lambda: cam.svc.state == "connected")
    assert cam.fake.log.count("connect") == 2


async def test_busy_when_om_capture_has_it_and_release_then_take(tmp_path):
    h = Harness(tmp_path, FakeDriver(busy=True))
    h.svc.start()
    try:
        await h.wait(lambda: h.svc.state == "busy_elsewhere")
        assert "OM Capture" in h.svc.detail
        h.fake.busy = False
        await h.wait(lambda: h.svc.state == "connected")
        snap = await h.svc.release()
        assert snap["state"] == "released" and h.fake.log[-1] == "close"
        await asyncio.sleep(0.2)
        assert h.svc.state == "released"  # stays released: no auto-reconnect
        await h.svc.take()
        await h.wait(lambda: h.svc.state == "connected")
    finally:
        h.svc.stop()


async def test_stop_closes_the_connection(cam):
    cam.svc.start()
    await cam.wait(lambda: cam.svc.state == "connected")
    cam.svc.stop()
    assert cam.fake.connected is False and cam.fake.log[-1] == "close"


async def test_live_view_frames_only_while_someone_watches(cam):
    cam.svc.start()
    await cam.wait(lambda: cam.svc.state == "connected")
    await asyncio.sleep(0.2)
    assert cam.svc.frame_seq == 0
    cam.svc.live_watchers = 1
    await cam.wait(lambda: cam.svc.frame_seq >= 3)
    assert cam.svc.frame == cam.fake.jpeg


async def test_off_mode_does_nothing(tmp_path):
    svc = CameraService("off", FakeDriver, lambda *a, **k: None, inbox=tmp_path)
    svc.start()
    assert svc.state == "off"
    with pytest.raises(NotConnected):
        await svc.step("aperture", 1)


async def test_a_camera_photo_arrives_in_the_active_shoot_like_a_tethered_one(make_harness, fx):
    h = await make_harness(camera="mock", camera_poll_s=0.05)
    fake = h.app.camera._factory()
    fake.jpeg = (fx / "P9260002.JPG").read_bytes()
    s = await h.session()
    await h.wait(lambda: h.app.camera.state == "connected", 5, "camera connected")
    assert h.app.camera.current_destination() == h.app.ingest.watched_folder
    await h.app.camera.trigger()
    (cap,) = await h.n_captures(s, 1)
    assert cap.source_paths and "AA9290001.JPG" in cap.source_paths[0]


# --- the remote's camera buttons ---------------------------------------------------------------------
from aperture_ally.camera.remote import FIRST_PHOTO_NOTE, CameraFeedback, RemoteCamera  # noqa: E402


class Heard:
    def __init__(self):
        self.cues: list[str] = []
        self.said: list[str] = []

    async def cue(self, kind):
        self.cues.append(kind)

    async def speak(self, text):
        self.said.append(text)


@pytest.fixture
async def remote(cam):
    cam.svc.start()
    await cam.wait(lambda: cam.svc.state == "connected")
    heard = Heard()
    applied = []

    async def apply():
        applied.append(1)
        return "f 2.8, applied"

    r = RemoteCamera(cam.svc, CameraFeedback(heard.speak, heard.cue, 0.05), apply, repeat_delay_s=0.1, repeat_hz=50)
    return r, heard, cam, applied


async def test_rapid_presses_tick_each_time_and_speak_only_the_last_value(remote):
    r, heard, cam, _ = remote
    for _ in range(4):
        assert await r.press("up") is True
        await r.release("up")
    await asyncio.sleep(0.15)
    assert heard.cues == ["camera_tick"] * 4
    assert heard.said == ["f 3.5"]  # 5.6 → 5.0 → 4.5 → 4.0 → 3.5: only the final value is spoken
    assert cam.svc.values["aperture"] == "3.5"


async def test_holding_repeats_and_stops_at_the_end_of_the_range(remote):
    r, heard, _cam, _ = remote
    await r.press("zl")  # ISO down: Auto is already the bottom
    await asyncio.sleep(0.15)
    await r.release("zl")
    assert heard.cues[0] == "camera_end"
    await asyncio.sleep(0.1)
    assert heard.said[-1] == "ISO auto, lowest"
    heard.cues.clear()
    await r.press("right")
    await asyncio.sleep(0.3)  # held: repeats after 0.1 s
    await r.release("right")
    n = len(heard.cues)
    assert n >= 3 and set(heard.cues) == {"camera_tick"}
    await asyncio.sleep(0.1)
    assert len(heard.cues) == n  # released: no more steps


async def test_shutter_notes_the_slow_first_photo_apply_and_readout(remote):
    r, heard, _cam, applied = remote
    await r.press("a")
    await asyncio.sleep(0.02)
    assert heard.said == [FIRST_PHOTO_NOTE]
    await r.press("y")
    await asyncio.sleep(0.02)
    assert applied and heard.said[-1] == "f 2.8, applied"
    await r.press("plus")
    await asyncio.sleep(0.02)
    assert heard.said[-1] == "f 5.6, compensation zero, ISO auto"


async def test_camera_buttons_without_a_camera_say_so_once_then_just_bump(remote):
    r, heard, cam, _ = remote
    cam.fake.present = False
    await cam.wait(lambda: cam.svc.state == "asleep")
    await r.press("up")
    await r.press("up")
    await asyncio.sleep(0.02)
    assert heard.said == ["Camera asleep. Half-press the shutter to wake it."]
    assert heard.cues == ["camera_end"]
    assert await r.press("l") is False  # not a camera button: push-to-talk keeps it


async def test_y_applies_the_coachs_aperture_and_says_when_the_lens_cant(make_harness):
    h = await make_harness(camera="mock", camera_poll_s=0.05)
    await h.wait(lambda: h.app.camera.state == "connected", 5, "camera connected")
    assert await h.app.apply_camera_suggestion() == "Nothing to apply from the last photo."
    target = {"v": ("aperture", "2.8")}

    async def suggestion():
        return target["v"]

    h.app.camera_suggestion = suggestion
    assert await h.app.apply_camera_suggestion() == "f 2.8, applied."
    assert h.app.camera.values["aperture"] == "2.8"
    applied = [e for e in h.app.bus.recent if e["type"] == "camera.applied"][-1]["payload"]
    assert applied["before"] == "5.6" and applied["after"] == "2.8"
    target["v"] = ("aperture", "1.4")  # the simulated lens stops at f/1.8
    assert await h.app.apply_camera_suggestion() == "f 1.8: the lens can't go to f/1.4."


async def test_camera_api_steps_sets_triggers_and_serves_a_live_frame(make_harness):
    import httpx

    from aperture_ally.app import create_app

    h = await make_harness(camera="mock", camera_poll_s=0.05)
    app = create_app(h.app.settings, coach=h.app)
    await h.wait(lambda: h.app.camera.state == "connected", 5, "camera connected")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        snap = (await c.get("/api/camera")).json()
        assert snap["state"] == "connected" and snap["settings"]["aperture"]["display"] == "f/5.6"
        r = (await c.post("/api/camera/step", json={"setting": "aperture", "dir": -1})).json()
        assert r["display"] == "f/5" and r["source"] == "ui"
        assert (await c.post("/api/camera/step", json={"setting": "shutter", "dir": 1})).status_code == 422
        r = (await c.post("/api/camera/set", json={"setting": "iso", "value": "400"})).json()
        assert r["display"] == "ISO 400"
        assert (await c.post("/api/camera/set", json={"setting": "iso", "value": "7"})).status_code == 200  # nearest
        frame = await c.get("/api/camera/frame")
        assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg"
        assert (await c.post("/api/camera/trigger")).json()["first_photo"] is True
        assert (await c.post("/api/camera/apply")).json()["text"] == "Nothing to apply from the last photo."
        assert (await c.post("/api/camera/release")).json()["state"] == "released"
        assert (await c.post("/api/camera/step", json={"setting": "iso", "dir": 1})).status_code == 409
        assert (await c.get("/api/camera/live")).status_code == 409


async def test_a_quick_press_released_during_a_slow_camera_step_does_not_repeat(remote):
    """Found at the desk (2026-09-29): ZL/ZR tapped once ran to the end of the range."""
    r, heard, cam, _ = remote
    real_step = cam.svc.step

    async def slow_step(*a, **k):
        res = await real_step(*a, **k)
        await asyncio.sleep(0.1)  # a real body takes 50–150 ms to report the new value
        return res

    cam.svc.step = slow_step
    pressing = asyncio.create_task(r.press("zr"))
    await asyncio.sleep(0.02)
    await r.release("zr")  # released before the first step came back
    await pressing
    await asyncio.sleep(0.4)
    assert heard.cues == ["camera_tick"] and cam.svc.values["iso"] == "64"


async def test_remote_x_repeats_the_last_advice_not_a_camera_readout(make_harness):
    h = await make_harness(camera="mock", camera_poll_s=0.05)
    await h.app.on_remote_button("x", True)
    await h.wait(lambda: h.speech.spoken, 3, "notice spoken")
    assert h.speech.spoken[-1] == "Nothing to repeat yet."
    await h.app.audio.speak("Open to f/2.8 for a softer background.", lambda: True, {"kind": "advice"})
    await h.app.audio.speak("f 4.5", lambda: True, {"kind": "camera"})
    await h.app.on_remote_button("x", True)
    await h.wait(lambda: len(h.speech.spoken) >= 4, 3, "repeat spoken")
    assert h.speech.spoken[-1] == "Open to f/2.8 for a softer background."


def test_voice_commands_for_the_live_view_grid_and_applying_the_suggestion():
    from aperture_ally.audio.voice import parse_command

    assert parse_command("grid off") == ("grid", "off")
    assert parse_command("Turn the grid on.") == ("grid", "on")
    assert parse_command("hide the grid") == ("grid", "off")
    assert parse_command("show grid") == ("grid", "on")
    assert parse_command("apply it") == ("apply_suggestion", None)
    assert parse_command("Is the grid helping?")[0] == "question"


async def test_saying_grid_off_tells_the_screen(make_harness):
    h = await make_harness(camera="mock", camera_poll_s=0.05)
    s = await h.session()
    h.app.voice.transcriber.queue.append("grid off")
    await h.app.voice.press(s.id)
    await asyncio.sleep(0.3)
    await h.app.voice.release()
    await h.wait(lambda: any(e["type"] == "ui.grid" for e in h.app.bus.recent), 5, "ui.grid event")
    ev = next(e for e in h.app.bus.recent if e["type"] == "ui.grid")
    assert ev["payload"]["on"] is False
    await h.wait(lambda: "Grid off." in h.speech.spoken, 5, "confirmation spoken")
