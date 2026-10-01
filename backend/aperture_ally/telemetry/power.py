"""Power sampling for the telemetry log: what the Mac draws, what our processes cost, and the camera's battery.

No sudo needed. The Mac's battery gauge (ioreg AppleSmartBattery) gives charge, voltage and the instantaneous
current, so system draw ≈ V × I while on battery. `top`'s POWER column is macOS's per-process "energy impact"
(the Activity Monitor number). Samples carry context (live view on, camera state, theme) so a shoot's log can
answer "what does live view cost?" without a separate test. Not a lab measurement: system draw includes the
screen and everything else running.
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Any

_KEYS = ("CurrentCapacity", "MaxCapacity", "Voltage", "InstantAmperage", "Amperage", "IsCharging", "ExternalConnected",
         "Temperature", "TimeRemaining")
_LINE = re.compile(r'^\s*"(\w+)" = (.+)$')


def _signed(v: int) -> int:
    return v - (1 << 64) if v >= (1 << 63) else v  # ioreg prints negative currents as unsigned 64-bit


def parse_battery(text: str) -> dict[str, Any] | None:
    raw: dict[str, str] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m and m.group(1) in _KEYS:
            raw[m.group(1)] = m.group(2).strip()
    if "CurrentCapacity" not in raw:
        return None

    def num(k: str) -> int | None:
        try:
            return _signed(int(raw[k]))
        except (KeyError, ValueError):
            return None

    ma = num("InstantAmperage") if num("InstantAmperage") is not None else num("Amperage")
    mv = num("Voltage")
    external = raw.get("ExternalConnected") == "Yes"
    out: dict[str, Any] = {
        "percent": num("CurrentCapacity"),
        "charging": raw.get("IsCharging") == "Yes",
        "on_power_adapter": external,
        "current_ma": ma,
        "voltage_mv": mv,
        # Discharge current is negative; draw is only meaningful on battery (on the adapter the gauge shows charge).
        "draw_w": round(abs(ma) * mv / 1e6, 2) if ma is not None and mv and not external and ma < 0 else None,
        "temperature_c": round(num("Temperature") / 100, 1) if num("Temperature") else None,
    }
    tr = num("TimeRemaining")
    out["minutes_remaining"] = tr if tr is not None and 0 < tr < 6000 and not external else None
    return out


def mac_battery() -> dict[str, Any] | None:
    if sys.platform != "darwin":
        return None
    try:
        text = subprocess.run(["ioreg", "-rn", "AppleSmartBattery"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    return parse_battery(text)


def parse_top(text: str) -> dict[int, dict[str, float]]:
    """The last sample of `top -l 2 -stats pid,cpu,power` → {pid: {cpu, energy}}."""
    blocks = text.split("PID")
    out: dict[int, dict[str, float]] = {}
    if len(blocks) < 2:
        return out
    for line in blocks[-1].splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit():
            try:
                out[int(parts[0])] = {"cpu": float(parts[1]), "energy": float(parts[2])}
            except ValueError:
                continue
    return out


def process_energy(pids: dict[str, int]) -> dict[str, dict[str, float]]:
    """Energy impact and CPU % for named pids over ~1 s (macOS `top`)."""
    pids = {k: v for k, v in pids.items() if v}
    if sys.platform != "darwin" or not pids:
        return {}
    args = ["top", "-l", "2", "-s", "1", "-stats", "pid,cpu,power"]
    for p in pids.values():
        args += ["-pid", str(p)]
    try:
        text = subprocess.run(args, capture_output=True, text=True, timeout=8).stdout
    except Exception:
        return {}
    by_pid = parse_top(text)
    return {name: by_pid[p] for name, p in pids.items() if p in by_pid}
