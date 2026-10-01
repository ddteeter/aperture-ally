"""Provider adapter contract. Application code depends only on this module."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..prompt import ModelRequest


class ProviderUnavailable(Exception):
    """Network/auth/config failure: AI is unavailable; local features continue."""


class ProviderError(Exception):
    """Provider answered but the call failed (refusal, incomplete, bad request)."""


@dataclass
class ModelResponse:
    text: str
    model_resolved: str | None
    usage: dict[str, Any] = field(default_factory=dict)
    response_id: str | None = None
    latency_ms: float | None = None


class Provider(Protocol):
    name: str
    model: str | None

    async def generate(self, req: ModelRequest) -> ModelResponse: ...

    async def repair(self, req: ModelRequest, previous: ModelResponse, errors: list[str]) -> ModelResponse: ...


def repair_message(errors: list[str]) -> str:
    return (
        "Your previous JSON failed validation:\n- " + "\n- ".join(errors[:12])
        + "\nReturn the corrected JSON only, keeping everything else the same."
    )


def data_url(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def estimate_cost(usage: dict[str, Any], price) -> float | None:
    """USD for one call. Claude reports cache reads/writes *beside* input_tokens; OpenAI and Gemini report
    `cached_input_tokens` *within* input_tokens (discounted only when the price says how much)."""
    if price is None:
        return None
    pin = price.input_per_mtok
    inp = usage.get("input_tokens") or 0
    out = usage.get("output_tokens") or 0
    cost = inp * pin + out * price.output_per_mtok
    read = usage.get("cache_read_input_tokens") or 0
    write = usage.get("cache_creation_input_tokens") or 0
    cost += read * (price.cached_input_per_mtok if price.cached_input_per_mtok is not None else pin * 0.1)
    cost += write * (price.cache_write_per_mtok if price.cache_write_per_mtok is not None else pin * 1.25)
    cached = usage.get("cached_input_tokens") or 0
    if cached and price.cached_input_per_mtok is not None:
        cost -= cached * (pin - price.cached_input_per_mtok)
    return round(cost / 1e6, 6)
