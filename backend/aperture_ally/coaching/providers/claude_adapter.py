"""Anthropic Claude adapter (official ``anthropic`` Python SDK, Messages API).

Same contract as the OpenAI/Gemini adapters:
* images as base64 ``image`` blocks, each preceded by its label;
* structured output via ``output_config.format = {type: json_schema, schema}`` (our strict schema uses only
  supported keywords: objects with ``additionalProperties: false``, enums, ``anyOf`` null unions);
* adaptive thinking, with optional ``output_config.effort`` (latency/quality lever worth sweeping in evals);
* server-side refusal fallback (``fallbacks: "default"``, beta ``server-side-fallback-2026-07-01``) is on by
  default: a safety decline is re-run on Anthropic's recommended fallback model inside the same call. The
  model that actually answered is recorded as ``model_resolved`` (and ``usage.fallback_used``), so evals and
  telemetry never attribute a fallback's answer to the requested model. Disable with
  ``APERTURE_ALLY_CLAUDE_REFUSAL_FALLBACK=false``.
* one repair attempt re-sends the input plus the failed output and the validation errors (no prefill).
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from ..prompt import ModelRequest
from .base import ModelResponse, ProviderError, ProviderUnavailable, repair_message

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str | None, model: str, *, effort: str | None = None, timeout_s: float = 45.0,
                 max_tokens: int = 16000, refusal_fallback: bool = True):
        import anthropic

        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.refusal_fallback = refusal_fallback
        # api_key=None lets the SDK resolve ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile.
        kwargs: dict[str, Any] = {"timeout": timeout_s, "max_retries": 1}
        if api_key:
            kwargs["api_key"] = api_key
        self.client = anthropic.AsyncAnthropic(**kwargs)

    def _content(self, req: ModelRequest) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": req.context_text()}]
        for i, im in enumerate(req.images, 1):
            content.append({"type": "text", "text": f"Image {i}: [{im.role} {im.kind} region_id={im.region_id}] {im.label}"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.standard_b64encode(Path(im.path).read_bytes()).decode("utf-8")}})
        return content

    async def _call(self, req: ModelRequest, messages: list[dict[str, Any]]) -> ModelResponse:
        import anthropic

        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": req.schema}}
        if self.effort:
            output_config["effort"] = self.effort
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": req.instructions,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": output_config,
        }
        if self.refusal_fallback:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        t0 = time.monotonic()
        try:
            if self.refusal_fallback:
                resp = await self.client.beta.messages.create(**params)
            else:
                resp = await self.client.messages.create(**params)
        except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.AuthenticationError,
                anthropic.PermissionDeniedError, anthropic.RateLimitError, anthropic.OverloadedError,
                anthropic.ServiceUnavailableError, anthropic.InternalServerError) as exc:
            raise ProviderUnavailable(f"{type(exc).__name__}: {exc}") from exc
        except anthropic.APIError as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc

        fallback_used = any(getattr(b, "type", None) == "fallback" for b in resp.content) or any(
            getattr(it, "type", None) == "fallback_message" for it in (getattr(resp.usage, "iterations", None) or []))
        u = resp.usage
        usage: dict[str, Any] = {
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,  # includes thinking tokens
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None) or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", None) or 0,
            "total_tokens": (u.input_tokens or 0) + (u.output_tokens or 0),
            "fallback_used": int(fallback_used),
        }
        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            raise ProviderError(f"refusal (category={getattr(details, 'category', None)}): "
                                f"{getattr(details, 'explanation', '') or ''}")
        if resp.stop_reason == "max_tokens":
            raise ProviderError(f"output truncated at max_tokens={self.max_tokens}")
        text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")
        if not text:
            raise ProviderError(f"no text block in response (stop_reason={resp.stop_reason})")
        return ModelResponse(text=text, model_resolved=resp.model, usage=usage, response_id=resp.id,
                             latency_ms=(time.monotonic() - t0) * 1000)

    async def generate(self, req: ModelRequest) -> ModelResponse:
        return await self._call(req, [{"role": "user", "content": self._content(req)}])

    async def repair(self, req: ModelRequest, previous: ModelResponse, errors: list[str]) -> ModelResponse:
        messages = [
            {"role": "user", "content": self._content(req)},
            {"role": "assistant", "content": previous.text},
            {"role": "user", "content": repair_message(errors)},
        ]
        return await self._call(req, messages)
