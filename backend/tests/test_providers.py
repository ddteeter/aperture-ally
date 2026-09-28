"""Adapter contract tests with the SDK network call stubbed (no paid API use)."""

import json
from types import SimpleNamespace

import pytest

from aperture_ally.coaching.prompt import SYSTEM_ASSESS, ImageInput, ModelRequest
from aperture_ally.coaching.providers.base import ProviderUnavailable
from aperture_ally.domain.assessment import AssessmentResult, provider_json_schema


def _req(fx):
    return ModelRequest("assess", SYSTEM_ASSESS, {"task": "assess"},
                        [ImageInput("current", "overview", "whole_image", "full frame", str(fx / "P9260001.JPG"))],
                        "assessment", provider_json_schema(AssessmentResult))


async def test_openai_request_shape_and_usage(fx):
    from aperture_ally.coaching.providers.openai_adapter import OpenAIProvider

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
    # Reasoning shares max_output_tokens with the JSON; 2000 returned `incomplete` with no output.
    assert seen["max_output_tokens"] >= 25000 and "reasoning" not in seen
    assert seen["text"]["format"]["type"] == "json_schema" and seen["text"]["format"]["strict"] is True
    content = seen["input"][0]["content"]
    img = next(c for c in content if c["type"] == "input_image")
    assert img["detail"] == "high" and img["image_url"].startswith("data:image/jpeg;base64,")
    assert resp.model_resolved == "configured-model-2026"
    assert resp.usage == {"input_tokens": 1200, "output_tokens": 150, "total_tokens": 1350, "reasoning_tokens": 40}

    await p.repair(_req(fx), resp, ["bad region"])
    assert seen["input"][-2]["role"] == "assistant" and "bad region" in seen["input"][-1]["content"]

    p.effort = "low"
    await p.generate(_req(fx))
    assert seen["reasoning"] == {"effort": "low"}


async def test_openai_connection_error_is_unavailable(fx):
    import httpx
    import openai

    from aperture_ally.coaching.providers.openai_adapter import OpenAIProvider

    p = OpenAIProvider("sk-test", "m")

    async def create(**kw):
        raise openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))

    p.client.responses.create = create
    with pytest.raises(ProviderUnavailable):
        await p.generate(_req(fx))


async def test_gemini_request_shape(fx):
    from aperture_ally.coaching.providers.gemini_adapter import GeminiProvider

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
    # Thinking is billed as output and shares the output budget.
    assert resp.usage["output_tokens"] == 130 and resp.usage["reasoning_tokens"] == 10
    assert cfg.max_output_tokens >= 16000 and cfg.thinking_config is None
    p.thinking_level = "low"
    await p.generate(_req(fx))
    assert str(seen["config"].thinking_config.thinking_level).endswith("LOW")


def test_registry_refuses_unconfigured_providers(tmp_path):
    from aperture_ally.coaching.service import ProviderRegistry

    from .conftest import fast_settings

    reg = ProviderRegistry(fast_settings(tmp_path))
    with pytest.raises(ProviderUnavailable, match="APERTURE_ALLY_OPENAI_MODEL"):
        reg.get("openai")
    assert reg.configured() == {"mock": True, "openai": False, "gemini": False, "claude": False}


def _claude_resp(*, stop="end_turn", text='{"ok": true}', model="claude-opus-5", blocks=None, iterations=None):
    content = blocks if blocks is not None else [SimpleNamespace(type="thinking", thinking=""),
                                                 SimpleNamespace(type="text", text=text)]
    usage = SimpleNamespace(input_tokens=2100, output_tokens=380, cache_read_input_tokens=0,
                            cache_creation_input_tokens=0, iterations=iterations)
    return SimpleNamespace(id="msg_1", model=model, stop_reason=stop, content=content, usage=usage,
                           stop_details=SimpleNamespace(category="cyber", explanation="declined") if stop == "refusal" else None)


async def test_claude_request_shape_and_usage(fx):
    from aperture_ally.coaching.providers.claude_adapter import FALLBACK_BETA, ClaudeProvider

    p = ClaudeProvider("sk-ant-test", "claude-opus-5", effort="medium")
    seen = {}

    async def create(**kw):
        seen.update(kw)
        return _claude_resp()

    p.client.beta.messages.create = create
    resp = await p.generate(_req(fx))
    assert seen["model"] == "claude-opus-5" and seen["system"] == SYSTEM_ASSESS
    assert seen["thinking"] == {"type": "adaptive"}
    assert seen["output_config"]["format"]["type"] == "json_schema" and seen["output_config"]["effort"] == "medium"
    assert seen["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert seen["betas"] == [FALLBACK_BETA] and seen["fallbacks"] == "default"
    blocks = seen["messages"][0]["content"]
    img = next(b for b in blocks if b["type"] == "image")
    assert img["source"]["type"] == "base64" and img["source"]["media_type"] == "image/jpeg"
    assert blocks[0]["type"] == "text" and "Image 1" in blocks[1]["text"]
    assert resp.text == '{"ok": true}' and resp.model_resolved == "claude-opus-5"
    assert resp.usage["input_tokens"] == 2100 and resp.usage["fallback_used"] == 0

    await p.repair(_req(fx), resp, ["bad region"])
    assert [m["role"] for m in seen["messages"]] == ["user", "assistant", "user"]
    assert "bad region" in seen["messages"][-1]["content"]


async def test_claude_fallback_is_attributed_to_the_serving_model(fx):
    from aperture_ally.coaching.providers.claude_adapter import ClaudeProvider

    p = ClaudeProvider("sk-ant-test", "claude-opus-5")

    async def create(**kw):
        return _claude_resp(model="claude-opus-4-8",
                            blocks=[SimpleNamespace(type="fallback"), SimpleNamespace(type="text", text="{}")])

    p.client.beta.messages.create = create
    resp = await p.generate(_req(fx))
    assert resp.model_resolved == "claude-opus-4-8" and resp.usage["fallback_used"] == 1


async def test_claude_refusal_truncation_and_outage(fx):
    import anthropic
    import httpx

    from aperture_ally.coaching.providers.base import ProviderError
    from aperture_ally.coaching.providers.claude_adapter import ClaudeProvider

    p = ClaudeProvider("sk-ant-test", "claude-opus-5", refusal_fallback=False)
    calls = []

    async def create(**kw):
        calls.append(kw)
        return nxt.pop(0)

    p.client.messages.create = create  # fallback off → non-beta endpoint, no betas/fallbacks params
    nxt = [_claude_resp(stop="refusal"), _claude_resp(stop="max_tokens")]
    with pytest.raises(ProviderError, match=r"refusal.*cyber"):
        await p.generate(_req(fx))
    with pytest.raises(ProviderError, match="max_tokens"):
        await p.generate(_req(fx))
    assert "betas" not in calls[0] and "fallbacks" not in calls[0] and "effort" not in calls[0]["output_config"]

    async def down(**kw):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    p.client.messages.create = down
    with pytest.raises(ProviderUnavailable):
        await p.generate(_req(fx))


def test_claude_registry_and_replay_effort_spec(tmp_path):
    import sys
    from pathlib import Path

    from aperture_ally.coaching.service import ProviderRegistry

    from .conftest import fast_settings

    s = fast_settings(tmp_path, anthropic_api_key="sk-ant-test")
    assert ProviderRegistry(s).configured()["claude"] is True
    assert ProviderRegistry(s).get("claude").model == "claude-opus-5-5"
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from evals.session_replay import make_provider

    p, s2 = make_provider("claude:claude-sonnet-5@low", s)
    assert p.model == "claude-sonnet-5" and p.effort == "low" and s2.claude_effort == "low"
    with pytest.raises(SystemExit):
        make_provider("openai:x@low", s)


def test_empty_optional_settings_mean_default(tmp_path, monkeypatch):
    # .env.example documents `APERTURE_ALLY_CLAUDE_EFFORT=` (empty) as "API default"; it used to fail startup.
    from aperture_ally.config import Settings

    env = tmp_path / ".env"
    env.write_text("APERTURE_ALLY_CLAUDE_EFFORT=\nAPERTURE_ALLY_OPENAI_EFFORT=\nAPERTURE_ALLY_GEMINI_THINKING_LEVEL=\n")
    monkeypatch.setenv("APERTURE_ALLY_SESSION_BUDGET_USD", "")
    s = Settings(_env_file=env)
    assert s.claude_effort is None and s.openai_effort is None and s.gemini_thinking_level is None
    assert s.session_budget_usd is None
