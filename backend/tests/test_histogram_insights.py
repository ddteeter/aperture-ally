"""Plain-language histogram insights, clipped-pixel overlay and before/after tonality changes."""

import httpx
from PIL import Image

from aperture_ally.app import create_app
from aperture_ally.coaching.prompt import compact_measurements
from aperture_ally.domain.models import Region
from aperture_ally.fixtures_gen import REGIONS
from aperture_ally.imaging.evidence import build_evidence, ensure_clip_overlay
from aperture_ally.imaging.interpret import HOW_TO_READ, compare, interpret


def _ev(fx, tmp_path, name, region):
    return build_evidence(fx / name, tmp_path / name, [Region(**REGIONS[region])])


def test_glare_region_is_the_headline(fx, tmp_path):
    ev = _ev(fx, tmp_path, "P9260002.JPG", "mesh")
    assert len(ev["measurements"]["regions"]["r1"]["histogram"]) == 64       # region histogram kept
    i = interpret(ev["measurements"], {"r1": "forefoot mesh"})
    assert i["summary"].endswith("of the forefoot mesh is pure white")
    region = i["regions"][0]
    assert region["severity"] == "problem" and region["findings"][0]["zone"] == "clip_high"
    assert "glare" in region["findings"][0]["detail"] and i["how_to_read"] == HOW_TO_READ


def test_dark_and_clean_frames(fx, tmp_path):
    dark = interpret(_ev(fx, tmp_path, "P9260006.JPG", "heel")["measurements"])
    assert dark["overall"]["shape"] == "Very dark overall" and dark["overall"]["severity"] == "warn"
    clean = interpret(_ev(fx, tmp_path, "P9260005.JPG", "tread")["measurements"])
    assert clean["overall"]["severity"] in ("ok", "info")
    assert any("nothing is blown" in f["headline"] for f in clean["overall"]["findings"])


def test_compare_describes_the_retake(fx, tmp_path):
    before = _ev(fx, tmp_path, "P9260002.JPG", "mesh")["measurements"]
    after = _ev(fx, tmp_path, "P9260003.JPG", "mesh")["measurements"]
    lines = compare(before, after, {"r1": "forefoot mesh"})
    assert lines[0].startswith("Pure white in the forefoot mesh dropped from 55%")


def test_region_histograms_stay_out_of_the_prompt(fx, tmp_path):
    m = compact_measurements(_ev(fx, tmp_path, "P9260002.JPG", "mesh")["measurements"])
    assert "histogram" not in m["regions"]["r1"] and "histogram" not in m["global"]
    assert m["global"]["histogram_fifths"]


def test_clip_overlay_marks_blown_pixels(fx, tmp_path):
    ev = _ev(fx, tmp_path, "P9260002.JPG", "mesh")
    out = ensure_clip_overlay(fx / "P9260002.JPG", ev["overview"], tmp_path / "o.png")
    im = Image.open(out)
    assert im.mode == "RGBA" and im.size == (ev["overview"]["width"], ev["overview"]["height"])
    # the synthetic hotspot is centred at ~(1150, 760) of 2400x1600 → alpha > 0 and red there
    x, y = int(im.width * 1150 / 2400), int(im.height * 760 / 1600)
    r, _g, _b, a = im.getpixel((x, y))
    assert a > 100 and r == 255
    assert im.getpixel((5, 5))[3] == 0


async def test_api_serves_insights_overlay_and_changes(make_harness, fx):
    h = await make_harness()
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.n_captures(s, 1)
    await h.settled()
    h.drop(s, fx / "P9260003.JPG")
    await h.n_captures(s, 2)
    await h.settled()
    c1, c2 = await h.captures(s)
    app = create_app(h.app.settings, coach=h.app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        view = (await c.get(f"/api/captures/{c2.id}")).json()
        assert view["histogram_insights"]["regions"][0]["scope"] == "forefoot mesh"
        assert view["histogram_changes"]["baseline_seq"] == c1.seq
        assert any("dropped" in x for x in view["histogram_changes"]["changes"])
        img = await c.get(f"/api/captures/{c1.id}/image/clip_overlay")
        assert img.status_code == 200 and img.headers["content-type"] == "image/png"
        state = (await c.get(f"/api/sessions/{s.id}")).json()
        assert state["captures"][0]["evidence"]["has_clip_overlay"]
        assert state["captures"][0]["histogram_insights"]["summary"]
