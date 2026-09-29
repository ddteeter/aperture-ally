"""The coaching contract: what a vision model must return, and how it is validated.

Pydantic is the source of truth. ``provider_json_schema()`` derives a strict, provider-friendly JSON
Schema (all properties required, nullable via ``anyOf``/null, no ``additionalProperties``, $refs
inlined). Semantic checks that JSON Schema cannot express live in ``validate_semantics``.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SPOKEN_SOFT_LIMIT_WORDS = 45
SPOKEN_HARD_LIMIT_WORDS = 60
WHOLE_IMAGE = "whole_image"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CriterionResult(_Strict):
    criterion_id: str
    result: Literal["pass", "fail", "uncertain"]
    evidence: str


class Observation(_Strict):
    region_id: str = Field(description="A supplied crop id, or 'whole_image'")
    observation: str
    evidence_source: Literal["pixels", "measurement", "metadata", "user_context"]
    severity: Literal["info", "minor", "major", "blocking"]


class ExposureTarget(_Strict):
    """Optional *target* settings; the app computes the equivalent shutter deterministically."""

    f_number: float | None
    iso: float | None


class PrimaryAction(_Strict):
    instruction: str = Field(description="One physically achievable change with a declared frame of reference")
    explanation: str
    expected_effect: str
    tradeoff: str
    prerequisites: list[str]
    hold_constant: str | None = Field(description="What to keep the same so the retake isolates this change")
    exposure_target: ExposureTarget | None = Field(
        description="Only if the action is an aperture/ISO change; never state a shutter speed yourself"
    )


class Comparison(_Strict):
    baseline_capture_id: str
    outcome: Literal["improved", "worse", "mixed", "uncertain"]
    evidence: str


class AssessmentResult(_Strict):
    verdict: Literal["usable_candidate", "needs_retake", "uncertain"]
    criterion_results: list[CriterionResult]
    observations: list[Observation]
    primary_action: PrimaryAction | None
    alternative_causes: list[str]
    fixable_in_post: list[str] = Field(description="Issues probably fixable in editing (RAW-aware); never the "
                                                    "primary action. Empty list if none")
    comparison: Comparison | None
    question_for_user: str | None
    teaching_prompt: str | None = Field(description="Only when the request asks for one; otherwise null")
    spoken_text: str


class ConversationAnswer(_Strict):
    answer: str = Field(description="Full answer for the screen")
    spoken_text: str = Field(description="Short spoken version, normally under 45 words")
    needs_new_photo: bool


# --- JSON schema for providers ---------------------------------------------------------------


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            return _inline_refs(copy.deepcopy(defs[name]), defs)
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


def _strictify(node: Any) -> Any:
    if isinstance(node, dict):
        node = {k: _strictify(v) for k, v in node.items() if k not in ("title", "default")}
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        return node
    if isinstance(node, list):
        return [_strictify(v) for v in node]
    return node


def provider_json_schema(model: type[BaseModel] = AssessmentResult) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    return _strictify(_inline_refs(raw, defs))


# --- semantic validation ---------------------------------------------------------------------


class ValidationContext(BaseModel):
    region_ids: set[str]
    criterion_ids: set[str]
    baseline_capture_id: str | None = None
    teaching_prompt_requested: bool = False
    metadata_available: bool = True
    exposure_metadata_available: bool = True


_SETTING_RX = re.compile(r"\b(f/\s?\d+(\.\d+)?|1/\d{1,5}\s?(s|sec)?\b|ISO\s?\d{2,6})", re.IGNORECASE)


def word_count(text: str) -> int:
    return len(text.split())


def parse_result(raw: str | dict[str, Any]) -> AssessmentResult:
    if isinstance(raw, str):
        return AssessmentResult.model_validate_json(raw)
    return AssessmentResult.model_validate(raw)


def validate_semantics(result: AssessmentResult, ctx: ValidationContext) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors block display/speech; warnings are recorded for evaluation."""
    errors: list[str] = []
    warnings: list[str] = []

    allowed_regions = ctx.region_ids | {WHOLE_IMAGE}
    for i, obs in enumerate(result.observations):
        if obs.region_id not in allowed_regions:
            errors.append(
                f"observations[{i}].region_id '{obs.region_id}' was not supplied; use one of {sorted(allowed_regions)}"
            )
        if obs.evidence_source == "metadata" and not ctx.metadata_available:
            errors.append(f"observations[{i}] cites metadata but no camera metadata was supplied")

    seen = [c.criterion_id for c in result.criterion_results]
    unknown = [c for c in seen if c not in ctx.criterion_ids]
    if unknown:
        errors.append(f"criterion_results reference unknown criteria {unknown}; valid ids: {sorted(ctx.criterion_ids)}")
    missing = ctx.criterion_ids - set(seen)
    if missing:
        errors.append(f"criterion_results missing {sorted(missing)}; report each criterion (uncertain is allowed)")
    if len(seen) != len(set(seen)):
        errors.append("criterion_results contains duplicate criterion ids")

    if ctx.baseline_capture_id is None and result.comparison is not None:
        errors.append("comparison must be null: no baseline image was supplied")
    if ctx.baseline_capture_id is not None:
        if result.comparison is None:
            errors.append("comparison is required: a baseline image was supplied")
        elif result.comparison.baseline_capture_id != ctx.baseline_capture_id:
            errors.append(f"comparison.baseline_capture_id must be '{ctx.baseline_capture_id}'")

    if not ctx.teaching_prompt_requested and result.teaching_prompt:
        errors.append("teaching_prompt must be null for this request")

    words = word_count(result.spoken_text)
    if not result.spoken_text.strip():
        errors.append("spoken_text is empty")
    elif words > SPOKEN_HARD_LIMIT_WORDS:
        errors.append(f"spoken_text has {words} words; keep it under {SPOKEN_SOFT_LIMIT_WORDS}")
    elif words > SPOKEN_SOFT_LIMIT_WORDS:
        warnings.append(f"spoken_text is {words} words (soft limit {SPOKEN_SOFT_LIMIT_WORDS})")

    if result.verdict == "usable_candidate" and any(c.result == "fail" for c in result.criterion_results):
        warnings.append("verdict usable_candidate while a criterion failed")
    if result.verdict == "needs_retake" and result.primary_action is None:
        warnings.append("needs_retake without a primary_action")

    if not ctx.exposure_metadata_available:
        text = " ".join(
            [result.spoken_text]
            + [o.observation for o in result.observations]
            + ([result.primary_action.instruction, result.primary_action.explanation] if result.primary_action else [])
        )
        if _SETTING_RX.search(text):
            warnings.append("mentions specific camera settings although exposure metadata was unavailable")
    return errors, warnings


def validate_output(raw: str | dict[str, Any], ctx: ValidationContext) -> tuple[AssessmentResult | None, list[str], list[str]]:
    try:
        result = parse_result(raw)
    except ValidationError as exc:
        return None, [f"schema: {e['loc']}: {e['msg']}" for e in exc.errors()][:20], []
    except ValueError as exc:
        return None, [f"not valid JSON: {exc}"], []
    errors, warnings = validate_semantics(result, ctx)
    return (result if not errors else None), errors, warnings
