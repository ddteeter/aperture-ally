"""Coloured status lines for the terminal commands (doctor, preflight).

Colour is added only for a TTY and can be forced or disabled with the usual conventions:
``NO_COLOR`` (any value) turns it off, ``FORCE_COLOR`` turns it on. The glyph and a status word
stay in the text, so the meaning survives without colour (and in logs or pasted output).
"""

from __future__ import annotations

import os
import sys
from typing import TextIO

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
STYLES = {
    "ok": "\033[32m",  # green
    "warn": "\033[33m",  # yellow
    "fail": "\033[31m",  # red
    "skip": "\033[90m",  # grey
}
GLYPHS = {"ok": "✔", "warn": "!", "fail": "✘", "skip": "–"}
WORDS = {"ok": "OK", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}


def use_color(stream: TextIO | None = None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    stream = stream or sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)()) and os.environ.get("TERM") != "dumb"


def paint(text: str, *codes: str, color: bool) -> str:
    prefix = "".join(codes)
    return f"{prefix}{text}{RESET}" if color and prefix else text


def status_line(level: str, name: str, detail: str, *, fix: str | None = None, color: bool | None = None) -> str:
    """`` ✔ OK    name: detail`` with the glyph, word and name coloured by level; the fix on its own line."""
    color = use_color() if color is None else color
    style = STYLES[level]
    head = paint(f"{GLYPHS[level]} {WORDS[level]:<4}", BOLD, style, color=color)
    label = paint(name, style if level != "ok" else "", BOLD if level in ("fail", "warn") else "", color=color)
    line = f" {head}  {label}: {paint(detail, DIM, color=color) if level == 'skip' else detail}"
    if fix:
        line += "\n" + " " * 9 + paint(f"→ {fix}", style, color=color)
    return line


def verdict_line(text: str, level: str, *, color: bool | None = None) -> str:
    color = use_color() if color is None else color
    return paint(text, BOLD, STYLES[level], color=color)
