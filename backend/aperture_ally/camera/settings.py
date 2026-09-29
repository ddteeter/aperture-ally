"""The three settings the remote changes (aperture, exposure compensation, ISO): order, step, display, speech.

Values are the camera's own strings (libgphoto2 choice labels such as "2.8", "0.7", "Auto"). Steps walk the
camera's choice list, so a step is whatever the camera uses (⅓ stop on the E-M1 II). The aperture list the
camera reports is the body's full range (f/1.0–f/91), not the lens's: the lens limit is found by setting a value
and reading it back (see CameraService.step).
"""

from __future__ import annotations

from typing import Literal

Setting = Literal["aperture", "exposurecompensation", "iso"]
SETTINGS: tuple[Setting, ...] = ("aperture", "exposurecompensation", "iso")
LABEL = {"aperture": "Aperture", "exposurecompensation": "Exposure comp.", "iso": "ISO"}


def _num(v: str) -> float | None:
    try:
        return float(v.strip().lstrip("fF/").replace(",", "."))
    except ValueError:
        return None


def ordered(setting: Setting, choices: list[str]) -> list[str]:
    """Choices in stepping order: aperture wide → narrow, compensation low → high, ISO Auto first then low → high.
    Labels the camera lists that aren't numbers (other than ISO Auto) are dropped."""
    numeric = [c for c in choices if _num(c) is not None]
    out = sorted(dict.fromkeys(numeric), key=lambda c: _num(c) or 0.0)
    if setting == "iso":
        auto = [c for c in choices if c.strip().lower() == "auto"]
        return auto[:1] + out
    return out


def index_of(value: str, order: list[str]) -> int | None:
    """Position of `value` in `order`, matching numerically ("8" == "8.0") and falling back to the nearest."""
    if value in order:
        return order.index(value)
    if value.strip().lower() == "auto":
        return next((i for i, c in enumerate(order) if c.strip().lower() == "auto"), None)
    v = _num(value)
    nums = [(i, _num(c)) for i, c in enumerate(order) if _num(c) is not None]
    if v is None or not nums:
        return None
    return min(nums, key=lambda t: abs((t[1] or 0.0) - v))[0]


def step(value: str, order: list[str], direction: int) -> tuple[str, bool]:
    """The next value one step in `direction` (+1 up the order, −1 down) and whether that hits the end."""
    i = index_of(value, order)
    if i is None or not order:
        return value, True
    j = max(0, min(len(order) - 1, i + direction))
    return order[j], j == i


def _thirds(v: float) -> str:
    """0.7 → "⅔", 1.3 → "1⅓", 2 → "2"."""
    n = round(abs(v) * 3)
    whole, rem = divmod(n, 3)
    frac = {0: "", 1: "⅓", 2: "⅔"}[rem]
    return f"{whole if whole or not frac else ''}{frac}" or "0"


def display(setting: Setting, value: str | None) -> str:
    """What the stage and panel show: f/2.8 · +⅔ · ±0.0 · ISO Auto · ISO 200."""
    if value is None:
        return "—"
    if setting == "aperture":
        v = _num(value)
        return f"f/{v:g}" if v is not None else value
    if setting == "exposurecompensation":
        v = _num(value)
        if v is None:
            return value
        if round(v * 3) == 0:
            return "±0.0"
        return f"{'+' if v > 0 else '−'}{_thirds(v)}"
    return "ISO Auto" if value.strip().lower() == "auto" else f"ISO {value}"


def end_word(setting: Setting, direction: int) -> str:
    """How the end of the range is named when you press past it."""
    if setting == "aperture":
        return "widest" if direction < 0 else "narrowest"
    if setting == "iso":
        return "lowest" if direction < 0 else "highest"
    return "end of range"


def spoken(setting: Setting, value: str, *, end: str | None = None) -> str:
    """What the coach says once you stop pressing: "f 2.8", "plus two thirds", "ISO auto" (+ ", widest")."""
    suffix = f", {end}" if end else ""
    if setting == "aperture":
        v = _num(value)
        return (f"f {v:g}" if v is not None else value) + suffix
    if setting == "exposurecompensation":
        v = _num(value)
        if v is None:
            return value + suffix
        n = round(abs(v) * 3)
        if n == 0:
            return "compensation zero" + suffix
        whole, rem = divmod(n, 3)
        parts = [str(whole)] if whole else []
        if rem:
            parts.append(("and a third" if rem == 1 else "and two thirds") if whole
                         else ("one third" if rem == 1 else "two thirds"))
        return f"{'plus' if v > 0 else 'minus'} {' '.join(parts)}" + suffix
    return ("ISO auto" if value.strip().lower() == "auto" else f"ISO {value}") + suffix
