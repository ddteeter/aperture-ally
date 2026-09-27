"""Framing similarity: calibrates ``COMPARABLE`` on synthetic fixtures (same scene vs reframed/zoomed/other)."""

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from aperture_ally.imaging import framing as F


def _overview(fx: Path, name: str, out: Path, fn=None) -> Path:
    img = cv2.imread(str(fx / name))
    if fn:
        img = fn(img)
    img = cv2.resize(img, (1600, round(1600 * img.shape[0] / img.shape[1])), interpolation=cv2.INTER_AREA)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img)
    return out


def _shift(fx_: float, fy_: float):
    def f(img):
        h, w = img.shape[:2]
        return cv2.warpAffine(img, np.float32([[1, 0, fx_ * w], [0, 1, fy_ * h]]), (w, h),
                              borderMode=cv2.BORDER_REPLICATE)
    return f


def _zoom(z: float):
    def f(img):
        h, w = img.shape[:2]
        cw, ch = int(w / z), int(h / z)
        x0, y0 = (w - cw) // 2, (h - ch) // 2
        return cv2.resize(img[y0:y0 + ch, x0:x0 + cw], (w, h))
    return f


def _relight(img):  # light moved/reshaped: a strong left-to-right falloff across the frame
    ramp = np.linspace(0.6, 1.3, img.shape[1], dtype=np.float32)[None, :, None]
    return np.clip(img * ramp, 0, 255).astype(np.uint8)


def _other_fabric(_img):  # a different knit: other pitch, cell size, colour and noise
    rng = np.random.default_rng(11)
    yy, xx = np.mgrid[0:1600, 0:2400].astype(np.float32)
    weave = np.sin(xx / 4.3) * np.sin(yy / 4.3) * 30 + rng.normal(0, 5, xx.shape)
    holes = ((xx.astype(int) // 19 + yy.astype(int) // 19) % 2) * 15
    return np.stack([np.clip(c + weave + holes, 0, 255) for c in (50, 60, 150)], -1).astype(np.uint8)


def _gain(g: float):
    return lambda img: np.clip(img.astype(np.float32) * g, 0, 255).astype(np.uint8)


@pytest.fixture(scope="module")
def ov(fx, tmp_path_factory):
    d = tmp_path_factory.mktemp("overviews")

    def make(name: str, fn=None, tag: str = "") -> Path:
        return _overview(fx, name, d / f"{tag}{name}", fn)
    return make


def score(a: Path, b: Path) -> float:
    return F.framing_score(a, b)


def test_same_framing_with_exposure_change_is_comparable(ov):
    assert score(ov("P9260006.JPG"), ov("P9260007.JPG")) >= F.COMPARABLE  # underexposed vs normal
    hero = ov("P9260001.JPG")
    assert score(hero, ov("P9260001.JPG", _gain(1.6), "bright_")) >= F.COMPARABLE
    assert score(hero, ov("P9260001.JPG", _gain(0.5), "dark_")) >= F.COMPARABLE
    assert score(hero, hero) > 0.99


def test_small_shift_and_focus_change_are_comparable(ov):
    hero = ov("P9260001.JPG")
    assert score(hero, ov("P9260001.JPG", _shift(0.05, 0), "sx_")) >= F.COMPARABLE
    assert score(hero, ov("P9260001.JPG", _shift(0.05, 0.04), "sxy_")) >= F.COMPARABLE
    assert score(ov("P9260004.JPG"), ov("P9260005.JPG")) >= F.COMPARABLE  # soft vs sharp outsole


def test_zoom_crop_and_other_scenes_are_not_comparable(ov):
    hero = ov("P9260001.JPG")
    for z in (1.3, 1.6, 2.0):
        assert score(hero, ov("P9260001.JPG", _zoom(z), f"z{z}_")) < F.COMPARABLE, z
    assert score(hero, ov("P9260005.JPG")) < F.COMPARABLE  # hero vs outsole
    assert score(hero, ov("P9260002.JPG")) < F.COMPARABLE  # hero vs mesh close-up
    assert score(hero, ov("P9260001.JPG", lambda i: cv2.rotate(i, cv2.ROTATE_180), "rot_")) < F.COMPARABLE
    portrait = ov("P9260001.JPG", lambda i: cv2.rotate(i, cv2.ROTATE_90_CLOCKWISE), "portrait_")
    assert score(hero, portrait) == 0.0  # different aspect ratio: another crop entirely


def test_fabric_close_up_retakes_are_comparable(ov):
    """Texture-dominated frames: the same close-up with the light moved must still read as the same framing."""
    mesh_glare, mesh_fixed = ov("P9260002.JPG"), ov("P9260003.JPG")
    assert score(mesh_glare, mesh_fixed) >= F.COMPARABLE  # basic_loop retake: hotspot moved off the weave
    assert score(mesh_fixed, ov("P9260003.JPG", _relight, "relit_")) >= F.COMPARABLE
    assert score(mesh_fixed, ov("P9260003.JPG", _shift(0.05, 0.02), "mshift_")) >= F.COMPARABLE
    assert not F._signature(mesh_fixed).layout_reliable  # detected as texture-dominated


def test_fabric_zoom_and_other_fabric_are_not_comparable(ov):
    mesh = ov("P9260003.JPG")
    for z in (1.15, 1.3, 1.5):
        assert score(mesh, ov("P9260003.JPG", _zoom(z), f"mz{z}_")) < F.COMPARABLE, z
    assert score(mesh, ov("P9260003.JPG", _other_fabric, "fabric2_")) < F.COMPARABLE
    assert score(mesh, ov("P9260004.JPG")) < F.COMPARABLE  # outsole tread


def test_score_is_symmetric_and_deterministic(ov):
    pairs = [(ov("P9260001.JPG"), ov("P9260002.JPG")), (ov("P9260002.JPG"), ov("P9260003.JPG"))]
    for a, b in pairs:
        results = set()
        for x, y in ((a, b), (b, a), (a, b)):
            F._score_cache.clear()
            results.add(score(x, y))
        assert len(results) == 1, results


@pytest.mark.parametrize("pair", [("P9260001.JPG", "P9260001.JPG"), ("P9260002.JPG", "P9260003.JPG")])
def test_score_is_fast_and_cached(ov, pair):
    a, b = ov(pair[0]), ov(pair[1], _shift(0.03, 0), "fast_")
    for p in (a, b):
        F.write_signature(p)  # as build_evidence does
    score(a, a)  # warm up OpenCV

    def timed() -> float:
        F._score_cache.clear()
        F._sig_cache.clear()
        t0 = time.perf_counter()
        score(a, b)
        return (time.perf_counter() - t0) * 1000

    stored = sorted(timed() for _ in range(5))
    assert stored[2] < 30, stored  # request time: signatures come from the evidence folder
    cold = []
    for _ in range(5):
        for p in (a, b):
            F.signature_file(p).unlink(missing_ok=True)
        cold.append(timed())
    assert sorted(cold)[2] < 60, cold  # first use on old evidence: both overviews decoded (~25 ms nominal)
    assert F.signature_file(a).exists()  # ...and stored for next time
    t0 = time.perf_counter()
    score(b, a)  # pair cache is order-independent
    assert (time.perf_counter() - t0) * 1000 < 2


def test_stored_signature_is_refreshed_when_the_overview_changes(ov, tmp_path):
    p = tmp_path / "overview.jpg"
    p.write_bytes(ov("P9260001.JPG").read_bytes())
    F.write_signature(p)
    import os

    st = F.signature_file(p).stat()
    os.utime(F.signature_file(p), ns=(st.st_atime_ns, st.st_mtime_ns - 10**9))  # older than the overview
    assert F._load_signature(p) is None
    F._sig_cache.clear()
    F._signature(p)
    assert F._load_signature(p) is not None


def test_framing_between_handles_missing_overviews(ov, tmp_path):
    ev = {"overview": {"path": str(ov("P9260001.JPG"))}}
    assert F.framing_between(ev, {}) is None
    assert F.framing_between(ev, {"overview": {"path": str(tmp_path / "gone.jpg")}}) is None
    assert F.framing_between(ev, ev) == {"score": 1.0, "comparable": True}


def test_recovered_photo_hint_uses_best_matching_other_shot(ov):
    from aperture_ally.comparison import attribution_hint
    from aperture_ally.domain.models import Capture, ShotRequirement

    shots = {sid: ShotRequirement(id=sid, session_id="s", title=sid.title()) for sid in ("hero", "outsole", "upper")}

    def cap(seq, shot, path, **kw):
        return Capture(id=f"c{seq}", session_id="s", seq=seq, shot_id=shot,
                       evidence={"overview": {"path": str(path)}}, **kw)

    caps = [cap(1, "hero", ov("P9260001.JPG")), cap(2, "outsole", ov("P9260005.JPG")),
            cap(3, "upper", ov("P9260004.JPG"), attribution_ambiguous=True, recovered=True)]
    hint = attribution_hint(caps[2], caps, shots)  # outsole photo filed under "upper" at startup
    assert hint["shot_id"] == "outsole" and hint["matched_capture_seq"] == 2
    assert hint["framing_score"] >= F.COMPARABLE and hint["seconds_after_switch"] is None
    caps.append(cap(4, "upper", ov("P9260005.JPG", tag="again_")))  # its own shot matches at least as well
    assert attribution_hint(caps[2], caps, shots) is None
    lone = cap(5, "upper", ov("P9260002.JPG"), attribution_ambiguous=True)
    assert attribution_hint(lone, [*caps, lone], shots) is None  # nothing similar elsewhere


def test_texture_frames_do_not_produce_misleading_hints(ov):
    from aperture_ally.comparison import attribution_hint
    from aperture_ally.domain.models import Capture, ShotRequirement

    shots = {sid: ShotRequirement(id=sid, session_id="s", title=sid.title()) for sid in ("hero", "upper", "trim")}

    def cap(seq, shot, path, **kw):
        return Capture(id=f"c{seq}", session_id="s", seq=seq, shot_id=shot,
                       evidence={"overview": {"path": str(path)}}, **kw)

    mesh = ov("P9260003.JPG")
    # Same fabric, but another shot framed it tighter: the texture does not line up, so no hint.
    trim = cap(1, "trim", ov("P9260003.JPG", _zoom(1.5), "trimzoom_"))
    found = cap(2, "hero", mesh, attribution_ambiguous=True, recovered=True)
    assert attribution_hint(found, [trim, found], shots) is None
    # The same close-up really was shot for "upper": a near-certain texture match is worth a hint.
    upper = cap(3, "upper", ov("P9260002.JPG"))
    hint = attribution_hint(found, [trim, upper, found], shots)
    assert hint["shot_id"] == "upper" and hint["matched_capture_seq"] == 3 and hint["framing_score"] >= 0.85
    # After a shot switch the previous shot is named, but a non-match is not reported as a "matched" photo.
    switched = cap(4, "hero", mesh, attribution_ambiguous=True,
                   attribution_context={"previous_shot_id": "trim", "seconds_after_switch": 1.2})
    hint = attribution_hint(switched, [trim, switched], shots)
    assert hint["shot_id"] == "trim" and hint["seconds_after_switch"] == 1.2
    assert hint["matched_capture_seq"] is None and hint["framing_score"] is None
