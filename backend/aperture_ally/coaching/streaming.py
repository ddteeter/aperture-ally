"""Speaking advice while the model is still writing it.

Measured on Sonnet 5.5 (2026-09-28): ~6 s of each coaching call went into the detailed JSON fields before
`spoken_text`, the last field. With `spoken_text` placed right after `verdict` in the schema, the sentence Drew
hears is complete ~0.5 s into the JSON and is spoken while the rest streams in.
"""

from __future__ import annotations

import json
import re
from typing import Any

SPOKEN_FIRST = ("verdict", "spoken_text")


def spoken_first_schema(schema: dict[str, Any], lead: tuple[str, ...] = SPOKEN_FIRST) -> dict[str, Any]:
    """Same schema with `lead` properties first (structured output follows property order)."""
    props = schema.get("properties", {})
    order = [k for k in lead if k in props] + [k for k in props if k not in lead]
    out = dict(schema)
    out["properties"] = {k: props[k] for k in order}
    if "required" in schema:
        out["required"] = [k for k in order if k in schema["required"]]
    return out


_STRING_END = re.compile(r'(?<!\\)(?:\\\\)*"')


def completed_string_field(partial_json: str, key: str) -> str | None:
    """Value of a top-level string field once its closing quote has streamed in, else None.

    Tolerant of a partial document: only the `"key": "…"` span has to be complete. Escapes are decoded.
    """
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*"', partial_json)
    if not m:
        return None
    rest = partial_json[m.end():]
    end = _STRING_END.search(rest)
    if not end:
        return None
    raw = rest[:end.end() - 1]
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return None
