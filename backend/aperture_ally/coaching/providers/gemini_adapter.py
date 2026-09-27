"""Gemini adapter (google-genai SDK) implementing the same contract as the OpenAI adapter.

Uses ``response_mime_type=application/json`` + ``response_json_schema`` and per-image
``media_resolution``. Verified against the installed SDK's type signatures, not live calls.

Thinking tokens share ``max_output_tokens`` and are billed as output, so ``output_tokens`` here is
candidates + thoughts (as OpenAI and Claude report it). ``thinking_level`` is optional; None = the
model's default (medium on gemini-3.8-flash, minimal on gemini-3.5-flash-lite).
"""

from __future__ import annotations

import time
from pathlib import Path

from ..prompt import ModelRequest
from .base import ModelResponse, ProviderError, ProviderUnavailable, repair_message

_RES = {"low": "MEDIA_RESOLUTION_LOW", "medium": "MEDIA_RESOLUTION_MEDIUM", "high": "MEDIA_RESOLUTION_HIGH",
        "ultra_high": "MEDIA_RESOLUTION_ULTRA_HIGH"}


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, *, media_resolution: str = "high", timeout_s: float = 45.0,
                 max_output_tokens: int = 16000, thinking_level: str | None = None):
        from google import genai
        from google.genai import types

        self.types = types
        self.model = model
        self.media_resolution = media_resolution
        self.max_output_tokens = max_output_tokens
        self.thinking_level = thinking_level
        self.timeout_s = timeout_s
        self.client = genai.Client(api_key=api_key,
                                   http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))

    def _contents(self, req: ModelRequest) -> list:
        t = self.types
        parts = [t.Part.from_text(text=req.context_text())]
        for i, im in enumerate(req.images, 1):
            parts.append(t.Part.from_text(text=f"Image {i}: [{im.role} {im.kind} region_id={im.region_id}] {im.label}"))
            parts.append(t.Part.from_bytes(data=Path(im.path).read_bytes(), mime_type="image/jpeg",
                                           media_resolution={"level": _RES[self.media_resolution]}))
        return [t.Content(role="user", parts=parts)]

    async def _call(self, req: ModelRequest, contents: list) -> ModelResponse:
        t = self.types
        from google.genai import errors

        config = t.GenerateContentConfig(
            system_instruction=req.instructions,
            response_mime_type="application/json",
            response_json_schema=req.schema,
            max_output_tokens=self.max_output_tokens,
            thinking_config=t.ThinkingConfig(thinking_level=self.thinking_level) if self.thinking_level else None,
        )
        t0 = time.monotonic()
        try:
            resp = await self.client.aio.models.generate_content(model=self.model, contents=contents, config=config)
        except errors.ClientError as exc:
            if getattr(exc, "code", None) in (401, 403, 429):
                raise ProviderUnavailable(str(exc)) from exc
            raise ProviderError(str(exc)) from exc
        except errors.APIError as exc:
            raise ProviderError(str(exc)) from exc
        except Exception as exc:
            raise ProviderUnavailable(f"{type(exc).__name__}: {exc}") from exc
        um = resp.usage_metadata
        usage = {}
        if um:
            usage = {"input_tokens": um.prompt_token_count,
                     "output_tokens": (um.candidates_token_count or 0) + (um.thoughts_token_count or 0),
                     "reasoning_tokens": um.thoughts_token_count, "total_tokens": um.total_token_count}
        text = resp.text or ""
        if not text:
            finish = getattr((getattr(resp, "candidates", None) or [None])[0], "finish_reason", None)
            raise ProviderError(f"empty response (finish_reason: {finish}; prompt feedback: {resp.prompt_feedback})")
        return ModelResponse(text=text, model_resolved=resp.model_version or self.model, usage=usage,
                             response_id=getattr(resp, "response_id", None),
                             latency_ms=(time.monotonic() - t0) * 1000)

    async def generate(self, req: ModelRequest) -> ModelResponse:
        return await self._call(req, self._contents(req))

    async def repair(self, req: ModelRequest, previous: ModelResponse, errors: list[str]) -> ModelResponse:
        t = self.types
        contents = self._contents(req) + [
            t.Content(role="model", parts=[t.Part.from_text(text=previous.text)]),
            t.Content(role="user", parts=[t.Part.from_text(text=repair_message(errors))]),
        ]
        return await self._call(req, contents)
