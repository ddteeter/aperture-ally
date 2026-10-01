"""Subject vs background (imaging/subject.py): the measurements, and Vision where it exists (macOS)."""

import cv2
import numpy as np
import pytest

from aperture_ally.imaging.subject import featureprint_distance, subject_measures, vision_available


def _scene(sharp_subject: bool, size=(600, 800)):
    """A textured box (the 'subject') on a textured background; one of the two blurred."""
    h, w = size
    rng = np.random.default_rng(0)
    tex = (rng.random((h, w)) * 255).astype(np.uint8)
    blurred = cv2.GaussianBlur(tex, (0, 0), 6)
    mask = np.zeros((h, w), bool)
    mask[150:450, 250:550] = True
    img = np.where(mask, tex if sharp_subject else blurred, blurred if sharp_subject else tex).astype(np.uint8)
    return img, mask


def test_background_softer_than_the_subject_reads_well_below_one():
    img, mask = _scene(sharp_subject=True)
    m = subject_measures(img, mask)
    assert m["background_to_subject_sharpness"] < 0.2
    assert m["fraction"] == pytest.approx(0.1875, abs=0.01)
    assert m["box"] == pytest.approx([0.312, 0.25, 0.375, 0.5], abs=0.01) and m["touches_edge"] == []


def test_subject_softer_than_the_background_reads_above_one_and_edge_contact_is_reported():
    img, mask = _scene(sharp_subject=False)
    assert subject_measures(img, mask)["background_to_subject_sharpness"] > 5
    mask2 = np.zeros_like(mask)
    mask2[200:600, 600:800] = True  # runs off the right and bottom edges
    assert subject_measures(img, mask2)["touches_edge"] == ["right", "bottom"]


def test_a_speck_is_not_a_subject():
    img, _ = _scene(True)
    tiny = np.zeros(img.shape, bool)
    tiny[10:15, 10:15] = True
    assert subject_measures(img, tiny) is None


def test_featureprint_distance():
    a = np.zeros(8, np.float32)
    b = np.ones(8, np.float32)
    assert featureprint_distance(a, a) == 0.0
    assert featureprint_distance(a, b) == pytest.approx(2.828, abs=0.001)
    assert featureprint_distance(a, None) is None
    assert featureprint_distance(a, np.zeros(4, np.float32)) is None


@pytest.mark.skipif(not vision_available(), reason="Apple Vision (macOS 14+) only")
def test_vision_runs_on_a_photo_and_writes_mask_and_featureprint(tmp_path, fx):
    from aperture_ally.imaging.subject import analyze

    src = fx / "P9260002.JPG"
    out = analyze(src, tmp_path)
    assert out is not None and isinstance(out["labels"], list)
    assert (tmp_path / "featureprint.npy").exists()
    assert out["ms"]["vision"] > 0
    if out["subject"] is not None:  # synthetic fixtures may or may not have a clear foreground
        assert (tmp_path / "subject_mask.png").exists() and 0 < out["subject"]["fraction"] <= 1


@pytest.mark.skipif(not vision_available(), reason="Apple Vision (macOS 14+) only")
async def test_the_coach_gets_the_subject_check(make_harness, fx):
    h = await make_harness()
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.n_captures(s, 1)
    await h.settled(15)
    (call,) = [c for c in await h.app.store.model_calls(s.id) if c.purpose == "assess"]
    ctx = call.request["context"]
    assert isinstance(ctx["subject_check"]["labels"], list)
    assert "8a." in call.request["instructions"]
