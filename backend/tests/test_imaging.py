"""Orientation/crop coordinates, measurements semantics, metadata normalization."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from aperture_ally.domain.models import Region
from aperture_ally.fixtures_gen import REGIONS
from aperture_ally.imaging.evidence import DecodeError, build_evidence, verify_decodable
from aperture_ally.imaging.measurements import region_comparable
from aperture_ally.imaging.metadata import MetadataReader, normalize


def test_orientation_normalized_crops_match(fx, tmp_path):
    """A region selected on the displayed image maps to the same pixels for an EXIF-rotated file."""
    region = [Region(**REGIONS["mesh"])]
    upright = build_evidence(fx / "P9260001.JPG", tmp_path / "a", region)
    rotated = build_evidence(fx / "P9260009.JPG", tmp_path / "b", region)
    assert (rotated["width"], rotated["height"]) == (upright["width"], upright["height"]) == (2400, 1600)
    assert rotated["crops"][0]["px_rect"] == upright["crops"][0]["px_rect"]
    a = np.asarray(Image.open(upright["crops"][0]["path"]), dtype=np.float32)
    b = np.asarray(Image.open(rotated["crops"][0]["path"]), dtype=np.float32)
    assert a.shape == b.shape
    assert np.abs(a - b).mean() < 6  # same content, only JPEG re-encoding differences
    ov = Image.open(rotated["overview"]["path"])
    assert ov.size[0] > ov.size[1]  # displayed landscape, like the upright original


def test_crop_px_rect_from_normalized_coordinates(fx, tmp_path):
    ev = build_evidence(fx / "P9260001.JPG", tmp_path, [Region(id="r1", x=0.25, y=0.5, w=0.25, h=0.25)])
    assert ev["crops"][0]["px_rect"] == [600, 800, 1200, 1200]
    assert ev["crops"][0]["native_resolution"] is True  # 600x400 below crop_max_edge


def test_auto_crop_when_no_region_and_labelled(fx, tmp_path):
    ev = build_evidence(fx / "P9260004.JPG", tmp_path, [])
    c = ev["crops"][0]
    assert c["id"] == "auto1" and c["source"] == "auto" and "not user-selected" in c["label"]
    # the most detailed tile is in the sharp (right) part of the outsole, not the blurred left part
    assert c["rect"][0] >= 0.5


def test_glare_and_blur_measurements_are_relative(fx, tmp_path):
    reg = [Region(**REGIONS["mesh"])]
    glare = build_evidence(fx / "P9260002.JPG", tmp_path / "g", reg)["measurements"]
    fixed = build_evidence(fx / "P9260003.JPG", tmp_path / "f", reg)["measurements"]
    assert glare["regions"]["r1"]["highlight_clip_fraction"] > 0.3
    assert fixed["regions"]["r1"]["highlight_clip_fraction"] < 0.01
    assert any("rendered 8-bit" in c for c in glare["caveats"])
    treg = [Region(**REGIONS["tread"])]
    soft = build_evidence(fx / "P9260004.JPG", tmp_path / "s", treg)["measurements"]["regions"]["r1"]
    sharp = build_evidence(fx / "P9260005.JPG", tmp_path / "h", treg)["measurements"]["regions"]["r1"]
    assert sharp["laplacian_var"] > 10 * soft["laplacian_var"]
    ok, reasons = region_comparable(sharp, soft, {"focal_length_mm": 25}, {"focal_length_mm": 25})
    assert ok and "indicative" in reasons[0]
    ok, reasons = region_comparable(sharp, soft, {"focal_length_mm": 25}, {"focal_length_mm": 40})
    assert not ok and "focal length" in reasons[0]


def test_truncated_jpeg_fails_decode(fx, tmp_path):
    data = (fx / "P9260001.JPG").read_bytes()
    part = tmp_path / "part.jpg"
    part.write_bytes(data[: len(data) // 2])
    with pytest.raises(DecodeError):
        verify_decodable(part)
    assert verify_decodable(fx / "P9260001.JPG") == (2400, 1600)


def test_metadata_normalization_never_invents(fx):
    r = MetadataReader()
    meta = r.read(fx / "P9260004.JPG")
    assert meta["f_number"] == pytest.approx(2.8)
    assert meta["exposure_time_s"] == pytest.approx(1 / 125)
    assert meta["iso"] == 200 and meta["exposure_program"] == "manual" and meta["flash_fired"] is False
    assert meta["exposure_known"] is True
    empty = r.read(fx / "NOEXIF01.JPG")
    assert empty["metadata_available"] is False and empty["exposure_known"] is False
    assert not ({"f_number", "iso", "exposure_time_s", "camera_model"} & set(empty))


def test_exiftool_group_prefixes_are_normalized():
    raw = {"EXIF:ExifIFD:FNumber": 4.0, "EXIF:ExifIFD:ExposureTime": 0.005, "EXIF:ExifIFD:ISO": 400,
           "EXIF:IFD0:Model": "E-M1MarkII", "EXIF:ExifIFD:Flash": 9, "EXIF:ExifIFD:ExposureProgram": 3,
           "EXIF:ExifIFD:DateTimeOriginal": "2026:09:26 10:00:00", "EXIF:ExifIFD:SubSecTimeOriginal": "5"}
    m = normalize(raw, "exiftool")
    assert m["f_number"] == 4.0 and m["iso"] == 400 and m["flash_fired"] is True
    assert m["exposure_program"] == "aperture_priority"
    assert m["datetime_original"] == "2026-09-26T10:00:00.500"
    assert "lens" not in m  # absent stays absent


def test_raw_unsupported_is_reported(tmp_path):
    from aperture_ally.imaging.raw import RawUnsupported, make_preview

    fake = tmp_path / "X.ORF"
    fake.write_bytes(b"not a raw" * 100)
    with pytest.raises(RawUnsupported):
        make_preview(fake, tmp_path / "p.jpg")
    assert not Path(tmp_path / "p.jpg").exists()
