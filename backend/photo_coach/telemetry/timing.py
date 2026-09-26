"""Stage timing.

Wall-clock UTC is persisted for cross-run correlation; within-process durations use the monotonic clock
(``mono_ns``) and are only compared within the same ``boot_id``. "speech_process_started" is when the
speech process launched, not proven audible onset; measure audible onset manually (docs/hardware-checks.md).
"""

from __future__ import annotations

import statistics
import time
import uuid
from typing import Any

from ..domain.models import utcnow

BOOT_ID = uuid.uuid4().hex[:12]

# Ordered pipeline stages for capture → coaching.
CAPTURE_STAGES = [
    "file_detected",
    "file_ready",
    "evidence_ready",
    "model_request_started",
    "model_response_received",
    "result_validated",
    "speech_requested",
    "speech_process_started",
    "speech_completed",
]

INTERVALS = {
    "detect_to_ready": ("file_detected", "file_ready"),
    "local_feedback (ready→evidence)": ("file_ready", "evidence_ready"),
    "model_call": ("model_request_started", "model_response_received"),
    "ready_to_validated": ("file_ready", "result_validated"),
    "ready_to_speech_process (first useful speech proxy)": ("file_ready", "speech_process_started"),
}


class Timer:
    def __init__(self, store):
        self.store = store  # AsyncStore

    async def mark(self, stage: str, *, at: tuple[int, str] | None = None, **ids: Any) -> int:
        """Persist a stage mark. ``at`` = (mono_ns, wall) recorded earlier, e.g. first detection."""
        mono, wall = at if at else (time.monotonic_ns(), utcnow())
        extra = ids.pop("extra", None)
        await self.store.add_timing(stage, wall, mono, BOOT_ID, extra=extra, **ids)
        return mono

    @staticmethod
    def now() -> tuple[int, str]:
        return time.monotonic_ns(), utcnow()


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(marks: list[dict]) -> dict[str, Any]:
    """Per-capture stage durations (ms) and p50/p95 per interval. First mark of each stage wins."""
    per_capture: dict[str, dict[str, tuple[int, str]]] = {}
    for m in marks:
        cid = m.get("capture_id")
        if not cid:
            continue
        per_capture.setdefault(cid, {}).setdefault(m["stage"], (m["mono_ns"], m["boot_id"]))
    rows = []
    for cid, stages in per_capture.items():
        row: dict[str, Any] = {"capture_id": cid, "stages": sorted(stages)}
        for name, (a, b) in INTERVALS.items():
            if a in stages and b in stages and stages[a][1] == stages[b][1]:
                row[name] = (stages[b][0] - stages[a][0]) / 1e6
        rows.append(row)
    summary = {}
    for name in INTERVALS:
        vals = [r[name] for r in rows if name in r]
        summary[name] = {
            "n": len(vals),
            "p50_ms": percentile(vals, 0.5),
            "p95_ms": percentile(vals, 0.95),
            "max_ms": max(vals) if vals else None,
            "mean_ms": statistics.fmean(vals) if vals else None,
        }
    return {"captures": rows, "summary": summary, "n_captures": len(rows)}
