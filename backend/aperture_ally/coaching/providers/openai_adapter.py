"""OpenAI Responses API adapter (verified against the installed ``openai`` SDK's request types).

Images are sent as base64 data URLs with a configurable ``detail`` level; structured output uses
``text.format = {type: json_schema, strict: true}``. ``store=False`` so no conversation state is kept
server-side; the single repair attempt re-sends the input plus the failed output and the errors.
"""

from __future__ import annotations

import time

from ..prompt import ModelRequest
from .base import ModelResponse, ProviderError, ProviderUnavailable, data_url, repair_message


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, *, image_detail: str = "high", timeout_s: float = 45.0,
                 max_output_tokens: int = 2000):
        from openai import AsyncOpenAI

        self.model = model
        self.image_detail = image_detail
        self.max_output_tokens = max_output_tokens
        self.client = AsyncOpenAI(api_key=api_key, timeout=timeout_s, max_retries=1)

    def _input(self, req: ModelRequest) -> list[dict]:
        content: list[dict] = [{"type": "input_text", "text": req.context_text()}]
        for i, im in enumerate(req.images, 1):
            content.append({"type": "input_text", "text": f"Image {i}: [{im.role} {im.kind} region_id={im.region_id}] {im.label}"})
            content.append({"type": "input_image", "image_url": data_url(im.path), "detail": self.image_detail})
        return [{"role": "user", "content": content}]

    async def _call(self, req: ModelRequest, input_items: list[dict]) -> ModelResponse:
        import openai

        t0 = time.monotonic()
        try:
            resp = await self.client.responses.create(
                model=self.model,
                instructions=req.instructions,
                input=input_items,
                text={"format": {"type": "json_schema", "name": req.schema_name, "schema": req.schema, "strict": True}},
                max_output_tokens=self.max_output_tokens,
                store=False,
            )
        except (openai.APIConnectionError, openai.APITimeoutError, openai.AuthenticationError,
                openai.PermissionDeniedError, openai.RateLimitError) as exc:
            raise ProviderUnavailable(f"{type(exc).__name__}: {exc}") from exc
        except openai.APIError as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
        if resp.status not in (None, "completed"):
            raise ProviderError(f"response status {resp.status}: {resp.incomplete_details}")
        usage = {}
        if resp.usage:
            usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
                     "total_tokens": resp.usage.total_tokens}
            details = getattr(resp.usage, "output_tokens_details", None)
            if details is not None and getattr(details, "reasoning_tokens", None) is not None:
                usage["reasoning_tokens"] = details.reasoning_tokens
        return ModelResponse(text=resp.output_text or "", model_resolved=resp.model, usage=usage,
                             response_id=resp.id, latency_ms=(time.monotonic() - t0) * 1000)

    async def generate(self, req: ModelRequest) -> ModelResponse:
        return await self._call(req, self._input(req))

    async def repair(self, req: ModelRequest, previous: ModelResponse, errors: list[str]) -> ModelResponse:
        items = self._input(req) + [
            {"role": "assistant", "content": previous.text},
            {"role": "user", "content": repair_message(errors)},
        ]
        return await self._call(req, items)
