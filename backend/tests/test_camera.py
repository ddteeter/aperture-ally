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
