"""Adapter contract tests with the SDK network call stubbed (no paid API use)."""

import json
from types import SimpleNamespace

import pytest

from photo_coach.coaching.prompt import SYSTEM_ASSESS, ImageInput, ModelRequest
from photo_coach.coaching.providers.base import ProviderUnavailable
from photo_coach.domain.assessment import AssessmentResult, provider_json_schema


def _req(fx):
    return ModelRequest("assess", SYSTEM_ASSESS, {"task": "assess"},
                        [ImageInput("current", "overview", "whole_image", "full frame", str(fx / "P9260001.JPG"))],
                        "assessment", provider_json_schema(AssessmentResult))


async def test_openai_request_shape_and_usage(fx):
    from photo_coach.coaching.providers.openai_adapter import OpenAIProvider

    p = OpenAIProvider("sk-test", "configured-model", image_detail="high")
    seen = {}

    async def create(**kw):
        seen.update(kw)
        return SimpleNamespace(status="completed", output_text='{"ok": true}', model="configured-model-2026",
                               id="resp_1", incomplete_details=None,
                               usage=SimpleNamespace(input_tokens=1200, output_tokens=150, total_tokens=1350,
                                                     output_tokens_details=SimpleNamespace(reasoning_tokens=40)))

    p.client.responses.create = create
    resp = await p.generate(_req(fx))
    assert seen["model"] == "configured-model" and seen["store"] is False
    assert seen["text"]["format"]["type"] == "json_schema" and seen["text"]["format"]["strict"] is True
    content = seen["input"][0]["content"]
    img = next(c for c in content if c["type"] == "input_image")
    assert img["detail"] == "high" and img["image_url"].startswith("data:image/jpeg;base64,")
    assert resp.model_resolved == "configured-model-2026"
    assert resp.usage == {"input_tokens": 1200, "output_tokens": 150, "total_tokens": 1350, "reasoning_tokens": 40}

    await p.repair(_req(fx), resp, ["bad region"])
    assert seen["input"][-2]["role"] == "assistant" and "bad region" in seen["input"][-1]["content"]


async def test_openai_connection_error_is_unavailable(fx):
    import httpx
    import openai

    from photo_coach.coaching.providers.openai_adapter import OpenAIProvider

    p = OpenAIProvider("sk-test", "m")

    async def create(**kw):
        raise openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))

    p.client.responses.create = create
    with pytest.raises(ProviderUnavailable):
        await p.generate(_req(fx))


async def test_gemini_request_shape(fx):
    from photo_coach.coaching.providers.gemini_adapter import GeminiProvider

    p = GeminiProvider("g-test", "configured-gemini", media_resolution="high")
    seen = {}

    async def generate_content(**kw):
        seen.update(kw)
        return SimpleNamespace(text=json.dumps({"ok": True}), model_version="configured-gemini-001",
                               response_id="r1", prompt_feedback=None,
                               usage_metadata=SimpleNamespace(prompt_token_count=900, candidates_token_count=120,
                                                              thoughts_token_count=10, total_token_count=1030))

    p.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    resp = await p.generate(_req(fx))
    cfg = seen["config"]
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema["type"] == "object"
    parts = seen["contents"][0].parts
    blobs = [x for x in parts if x.inline_data is not None]
    assert blobs and blobs[0].inline_data.mime_type == "image/jpeg"
    assert str(blobs[0].media_resolution.level).endswith("HIGH")
    assert resp.usage["input_tokens"] == 900 and resp.model_resolved == "configured-gemini-001"


def test_registry_refuses_unconfigured_providers(tmp_path):
    from photo_coach.coaching.service import ProviderRegistry

    from .conftest import fast_settings

    reg = ProviderRegistry(fast_settings(tmp_path))
    with pytest.raises(ProviderUnavailable, match="PHOTO_COACH_OPENAI_MODEL"):
        reg.get("openai")
    assert reg.configured() == {"mock": True, "openai": False, "gemini": False}
