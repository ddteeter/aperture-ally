"""Environment checks: `photo-coach doctor`. Never prints secrets."""

from __future__ import annotations

import ctypes
import importlib
import platform
import shutil
import subprocess
import sys
from typing import Any

from .config import Settings


def _check(name: str, ok: bool | None, detail: str = "", fix: str = "") -> dict[str, Any]:
    return {"name": name, "status": "ok" if ok else ("warn" if ok is None else "fail"), "detail": detail, "fix": fix}


def _import(mod: str) -> tuple[bool, str]:
    try:
        m = importlib.import_module(mod)
        return True, getattr(m, "__version__", "") or getattr(m, "version", "") or ""
    except Exception as exc:
        return False, str(exc).splitlines()[0][:160]


def _mac_permission(fn: str) -> bool | None:
    """AXIsProcessTrusted (Accessibility) / IOHIDCheckAccess (Input Monitoring) for this process."""
    if sys.platform != "darwin":
        return None
    try:
        if fn == "accessibility":
            lib = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
            lib.AXIsProcessTrusted.restype = ctypes.c_bool
            return bool(lib.AXIsProcessTrusted())
        lib = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/IOKit.framework/IOKit")
        lib.IOHIDCheckAccess.restype = ctypes.c_uint32
        lib.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
        return lib.IOHIDCheckAccess(1) == 0  # kIOHIDRequestTypeListenEvent; 0 = granted
    except Exception:
        return None


def run_checks(s: Settings, quick: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    mac = sys.platform == "darwin"
    arch = platform.machine()
    out.append(_check("platform", mac or None, f"{platform.platform()} ({arch})",
                      "" if mac else "Target is macOS; non-mac hosts run replay/mock only"))
    out.append(_check("arm64 native", (arch == "arm64") if mac else None, f"python {platform.python_version()} on {arch}",
                      "Use a native arm64 Python (uv python install 3.12) — not Rosetta" if mac and arch != "arm64" else ""))
    for mod in ("cv2", "numpy", "PIL", "rawpy", "watchdog", "openai", "google.genai"):
        ok, ver = _import(mod)
        out.append(_check(f"import {mod}", ok, ver, "" if ok else "uv sync"))
    et = shutil.which("exiftool")
    ver = ""
    if et:
        try:
            ver = subprocess.run([et, "-ver"], capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            pass
    out.append(_check("exiftool", bool(et) or None, ver or "not found (Pillow EXIF fallback; ORF metadata unavailable)",
                      "brew install exiftool"))
    # providers (presence only)
    out.append(_check("assessment provider", True, s.assess_provider))
    out.append(_check("OpenAI configured", (s.openai_api_key is not None and bool(s.openai_model)) or None,
                      f"key {'set' if s.openai_api_key else 'missing'}, model {s.openai_model or 'unset'}",
                      "set OPENAI_API_KEY and PHOTO_COACH_OPENAI_MODEL (from official docs)"))
    out.append(_check("Gemini configured", (s.gemini_api_key is not None and bool(s.gemini_model)) or None,
                      f"key {'set' if s.gemini_api_key else 'missing'}, model {s.gemini_model or 'unset'}",
                      "set GEMINI_API_KEY and PHOTO_COACH_GEMINI_MODEL (from official docs)"))
    out.append(_check("transcription", s.transcriber == "mock" or (bool(s.openai_api_key) and bool(s.transcription_model)) or None,
                      f"{s.transcriber} model={s.transcription_model or 'unset'}"))
    # audio output
    say = shutil.which("say")
    out.append(_check("speech: say", bool(say) if mac else None, f"provider={s.speech_provider}; say={'found' if say else 'missing'}"))
    if say and not quick:
        try:
            devs = subprocess.run([say, "-a", "?"], capture_output=True, text=True, timeout=5).stdout.strip()
            out.append(_check("audio output devices", True, devs[:800]))
        except Exception as exc:
            out.append(_check("audio output devices", None, str(exc)))
    # microphone
    ok, err = _import("sounddevice")
    if ok:
        try:
            import sounddevice as sd

            inputs = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
            default = sd.query_devices(kind="input")["name"] if inputs else None
            out.append(_check("input devices", bool(inputs) or None, f"default={default}; all={inputs[:8]}",
                              "grant Microphone permission to your terminal app"))
        except Exception as exc:
            out.append(_check("input devices", None, f"PortAudio: {exc}"))
    else:
        out.append(_check("sounddevice", None, err, "uv sync (PortAudio bundled on macOS wheels)"))
    # keys / permissions
    out.append(_check("global keys", True if s.global_keys == "pynput" else None,
                      f"mode={s.global_keys} key={s.ptt_key} ({s.ptt_mode})",
                      "PHOTO_COACH_GLOBAL_KEYS=pynput to enable (macOS)"))
    if mac:
        ok, err = _import("pynput")
        out.append(_check("pynput", ok, err))
        im = _mac_permission("input_monitoring")
        out.append(_check("Input Monitoring permission", im, "",
                          "System Settings → Privacy & Security → Input Monitoring → enable your terminal app"))
        ax = _mac_permission("accessibility")
        out.append(_check("Accessibility permission", ax if ax else None, "may be needed by pynput on some macOS versions",
                          "System Settings → Privacy & Security → Accessibility → enable your terminal app"))
    # storage
    try:
        s.data_dir.mkdir(parents=True, exist_ok=True)
        probe = s.data_dir / ".write_probe"
        probe.write_text("ok")
        probe.unlink()
        out.append(_check("data dir writable", True, str(s.data_dir)))
    except Exception as exc:
        out.append(_check("data dir writable", False, f"{s.data_dir}: {exc}"))
    fe = s.frontend_dist / "index.html"
    out.append(_check("frontend build", fe.exists() or None, str(fe), "cd frontend && npm ci && npm run build"))
    return out


def print_checks(checks: list[dict[str, Any]]) -> int:
    icon = {"ok": "✔", "warn": "!", "fail": "✘"}
    for c in checks:
        line = f" {icon[c['status']]} {c['name']}: {c['detail']}"
        if c["status"] != "ok" and c["fix"]:
            line += f"\n     → {c['fix']}"
        print(line)
    return 1 if any(c["status"] == "fail" for c in checks) else 0
