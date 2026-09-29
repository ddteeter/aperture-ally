"""Pure domain rules: exposure arithmetic, schema strictness, output validation."""

import json
import math

import pytest

from aperture_ally.domain.assessment import (
    AssessmentResult,
    ValidationContext,
    provider_json_schema,
    validate_output,
)
from aperture_ally.domain.exposure import (
    ExposureContext,
    equivalent_exposure,
    format_shutter,
    round_to_standard,
)

MANUAL = ExposureContext(light="continuous", exposure_mode="manual", iso_mode="manual", flash_fired=False)


def test_exposure_equivalence_aperture_change():
    eq = equivalent_exposure(1 / 125, 2.8, 200, new_f_number=8, ctx=MANUAL)
    assert eq.applicable
    assert eq.exact_duration_s == pytest.approx((1 / 125) * (8 / 2.8) ** 2)
    assert eq.rounded_label == "1/15 s"
    assert eq.stops_change == pytest.approx(math.log2((8 / 2.8) ** 2), abs=0.01)


def test_exposure_equivalence_iso_change_and_combined():
    eq = equivalent_exposure(1 / 60, 5.6, 200, new_iso=800, ctx=MANUAL)
    assert eq.exact_duration_s == pytest.approx(1 / 240)
    assert eq.rounded_label == "1/250 s"
    both = equivalent_exposure(1 / 60, 4, 200, new_f_number=8, new_iso=800, ctx=MANUAL)
    assert both.exact_duration_s == pytest.approx(1 / 60)  # +2 stops aperture, -2 stops ISO


@pytest.mark.parametrize("ctx,reason", [
    (ExposureContext(light="flash", exposure_mode="manual", iso_mode="manual"), "flash"),
    (ExposureContext(light="continuous", exposure_mode="aperture_priority", iso_mode="manual"), "not confirmed manual"),
    (ExposureContext(light="continuous", exposure_mode="manual", iso_mode="auto"), "auto ISO"),
    (ExposureContext(light="continuous", exposure_mode="manual", iso_mode="manual", flash_fired=True), "flash fired"),
    (ExposureContext(light="continuous", exposure_mode="manual", iso_mode="manual", illumination_unchanged=False), "illumination changed"),
    (ExposureContext(light="unknown", exposure_mode="manual", iso_mode="manual"), "continuous light"),
])
def test_exposure_refuses_inapplicable_context(ctx, reason):
    eq = equivalent_exposure(1 / 60, 4, 200, new_f_number=8, ctx=ctx)
    assert not eq.applicable
    assert eq.rounded_duration_s is None
    assert any(reason in r for r in eq.reasons)


def test_exposure_requires_known_metadata():
    eq = equivalent_exposure(None, 4, 200, new_f_number=8, ctx=MANUAL)
    assert not eq.applicable and "not all known" in eq.reasons[0]


def test_standard_rounding():
    assert format_shutter(round_to_standard(1 / 65)) == "1/60 s"
    assert format_shutter(round_to_standard(1 / 70)) == "1/80 s"  # nearest in stops, not in seconds
    assert format_shutter(round_to_standard(0.9)) == "1 s"
    assert format_shutter(round_to_standard(2.2)) == "2 s"


def _walk(node, fn):
    fn(node)
    if isinstance(node, dict):
        for v in node.values():
            _walk(v, fn)
    elif isinstance(node, list):
        for v in node:
            _walk(v, fn)


def test_provider_schema_is_strict():
    schema = provider_json_schema(AssessmentResult)
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema

    def check(n):
        if isinstance(n, dict) and n.get("type") == "object" and "properties" in n:
            assert n["additionalProperties"] is False
            assert set(n["required"]) == set(n["properties"])
        if isinstance(n, dict):
            assert "default" not in n

    _walk(schema, check)
    assert set(schema["properties"]["verdict"]["enum"]) == {"usable_candidate", "needs_retake", "uncertain"}


def _good(**over):
    base = {
        "verdict": "needs_retake",
        "criterion_results": [{"criterion_id": "c1", "result": "fail", "evidence": "hotspot"}],
        "observations": [{"region_id": "r1", "observation": "clipped", "evidence_source": "pixels", "severity": "major"}],
        "primary_action": {"instruction": "Move the light camera-left", "explanation": "x", "expected_effect": "y",
                           "tradeoff": "z", "prerequisites": [], "hold_constant": None, "exposure_target": None},
        "alternative_causes": [], "fixable_in_post": [], "comparison": None, "question_for_user": None,
        "teaching_prompt": None,
        "spoken_text": "Needs a retake. Move the light camera-left.",
    }
    base.update(over)
    return base


CTX = ValidationContext(region_ids={"r1"}, criterion_ids={"c1"})


def test_valid_output_passes():
    res, errors, warnings = validate_output(json.dumps(_good()), CTX)
    assert res is not None and errors == [] and warnings == []


def test_invented_region_rejected():
    bad = _good(observations=[{"region_id": "toe_box", "observation": "x", "evidence_source": "pixels", "severity": "minor"}])
    res, errors, _ = validate_output(bad, CTX)
    assert res is None and "toe_box" in errors[0]


def test_missing_and_unknown_criteria_rejected():
    res, errors, _ = validate_output(_good(criterion_results=[{"criterion_id": "c9", "result": "pass", "evidence": ""}]), CTX)
    assert res is None
    assert any("unknown criteria" in e for e in errors) and any("missing" in e for e in errors)


def test_comparison_consistency_with_baseline():
    comp = {"baseline_capture_id": "B", "outcome": "improved", "evidence": "less glare"}
    assert validate_output(_good(comparison=comp), CTX)[0] is None  # no baseline supplied
    with_b = ValidationContext(region_ids={"r1"}, criterion_ids={"c1"}, baseline_capture_id="B")
    assert validate_output(_good(), with_b)[0] is None  # baseline supplied but no comparison
    assert validate_output(_good(comparison={**comp, "baseline_capture_id": "X"}), with_b)[0] is None
    assert validate_output(_good(comparison=comp), with_b)[0] is not None


def test_teaching_prompt_only_when_requested():
    assert validate_output(_good(teaching_prompt="What will change?"), CTX)[0] is None
    ok = ValidationContext(region_ids={"r1"}, criterion_ids={"c1"}, teaching_prompt_requested=True)
    assert validate_output(_good(teaching_prompt="What will change?"), ok)[0] is not None


def test_spoken_text_length_limits():
    long = " ".join(["word"] * 70)
    res, errors, _ = validate_output(_good(spoken_text=long), CTX)
    assert res is None and "words" in errors[0]
    res, _, warnings = validate_output(_good(spoken_text=" ".join(["w"] * 50)), CTX)
    assert res is not None and warnings


def test_schema_violations_and_garbage():
    assert validate_output("not json", CTX)[0] is None
    assert validate_output(json.dumps({**_good(), "extra": 1}), CTX)[0] is None  # extra forbidden
    assert validate_output(json.dumps({**_good(), "verdict": "great"}), CTX)[0] is None


def test_metadata_fabrication_detection():
    no_meta = ValidationContext(region_ids={"r1"}, criterion_ids={"c1"}, metadata_available=False,
                                exposure_metadata_available=False)
    cites = _good(observations=[{"region_id": "whole_image", "observation": "shot at f/2.8",
                                 "evidence_source": "metadata", "severity": "info"}])
    assert validate_output(cites, no_meta)[0] is None
    invented = _good(spoken_text="You shot at 1/30 s and ISO 3200; use f/8.")
    res, _, warnings = validate_output(invented, no_meta)
    assert res is not None and any("camera settings" in w for w in warnings)
