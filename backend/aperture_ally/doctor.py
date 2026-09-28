"""Environment checks: `aperture-ally doctor`. Never prints secrets."""

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


def gamepad_check() -> dict[str, Any]:
    try:
        import hid

        from .input.gamepad import SWITCH_PRO

        found = hid.enumerate(*SWITCH_PRO)
    except Exception as exc:
        return _check("gamepad", None, f"hidapi: {exc}", "uv sync")
    return _check("gamepad", True if found else None,
                  f"{found[0].get('product_string')} connected" if found else "not connected",
                  "" if found else "8BitDo Micro: slide to S, press a button to wake it, pair it in Bluetooth settings")


def headset_mic_check(mic: str | None, output: str | None, always_open: bool = False) -> dict[str, Any]:
    """Recording from the headphones' own mic flips Bluetooth headphones into call mode: playback garbles
    and the first moments of speech are lost while it switches (seen with AirPods Pro). With the mic held
    open (APERTURE_ALLY_MIC_ALWAYS_OPEN) the switch happens once, at start-up, so that's the intended setup."""
    same = bool(mic and output and (mic == output or mic in output or output in mic))
    if same and always_open:
        return _check("microphone vs headphones", True, f"mic={mic}; headphones' own mic, held open (call mode)")
    return _check("microphone vs headphones", None if same else True,
                  f"mic={mic}; output={output}" + ("; the headphones' own mic" if same else ""),
                  "APERTURE_ALLY_MIC_ALWAYS_OPEN=true, or set APERTURE_ALLY_INPUT_DEVICE to the Mac's microphone"
                  if same else "")


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
    for mod in ("cv2", "numpy", "PIL", "rawpy", "watchdog", "openai", "google.genai", "anthropic"):
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
                      "set OPENAI_API_KEY and APERTURE_ALLY_OPENAI_MODEL (from official docs)"))
    out.append(_check("Gemini configured", (s.gemini_api_key is not None and bool(s.gemini_model)) or None,
                      f"key {'set' if s.gemini_api_key else 'missing'}, model {s.gemini_model or 'unset'}",
                      "set GEMINI_API_KEY and APERTURE_ALLY_GEMINI_MODEL (from official docs)"))
    out.append(_check("Claude configured", (s.anthropic_api_key is not None and bool(s.claude_model)) or None,
                      f"key {'set' if s.anthropic_api_key else 'missing (SDK may still use ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile)'}, "
                      f"model {s.claude_model or 'unset'}, effort {s.claude_effort or 'API default'}, "
                      f"refusal fallback {'on' if s.claude_refusal_fallback else 'off'}",
                      "set ANTHROPIC_API_KEY (or run `ant auth login`)"))
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
            output = sd.query_devices(kind="output")["name"] if sd.query_devices() else None
            out.append(headset_mic_check(s.input_device or default, output, always_open=s.mic_always_open))
        except Exception as exc:
            out.append(_check("input devices", None, f"PortAudio: {exc}"))
    else:
        out.append(_check("sounddevice", None, err, "uv sync (PortAudio bundled on macOS wheels)"))
    # keys / permissions
    out.append(_check("global keys", True if s.global_keys in ("pynput", "gamepad") else None,
                      f"mode={s.global_keys} key={s.gamepad_ptt if s.global_keys == 'gamepad' else s.ptt_key} "
                      f"({s.ptt_mode})",
                      "APERTURE_ALLY_GLOBAL_KEYS=gamepad (8BitDo Micro in S mode) or pynput (keyboard remote)"))
    if s.global_keys == "gamepad":
        out.append(gamepad_check())
    if mac and s.global_keys != "pynput":
        # Only the global key listener needs these; the browser keys and an 8BitDo in S mode (gamepad) don't.
        out.append(_check("Input Monitoring permission", True, f"not needed (global keys: {s.global_keys})"))
    elif mac:
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
    out.append(_check("frontend build", fe.exists() or None, str(fe),
                      "" if fe.exists() else "cd frontend && npm ci && npm run build"))
    return out


def print_checks(checks: list[dict[str, Any]]) -> int:
    from .term import status_line, verdict_line

    for c in checks:
        print(status_line(c["status"], c["name"], c["detail"], fix=c["fix"] if c["status"] != "ok" else None))
    fails = sum(c["status"] == "fail" for c in checks)
    warns = sum(c["status"] == "warn" for c in checks)
    summary = f"{fails} problem(s), {warns} warning(s)" if fails or warns else "All checks passed"
    print("\n" + verdict_line(summary, "fail" if fails else "warn" if warns else "ok"))
    return 1 if any(c["status"] == "fail" for c in checks) else 0
