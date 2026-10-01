"""Evidence caching: evidence depends on the image and the shot's selected regions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from concurrent.futures import Executor
from pathlib import Path
from typing import Any

from ..config import Settings
from ..domain.models import Capture, Region
from .evidence import build_evidence


def regions_key(regions: list[Region]) -> str:
    payload = json.dumps([r.model_dump() for r in regions], sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:10]


def primary_image(capture: Capture) -> Path | None:
    """Image used for evidence: the JPEG, else a RAW-derived preview."""
    if capture.jpeg_path:
        return Path(capture.jpeg_path)
    preview = capture.pairing.get("raw_preview_path")
    return Path(preview) if preview else None


async def ensure_evidence(
    capture: Capture, regions: list[Region], session_root: Path, settings: Settings, executor: Executor
) -> dict[str, Any]:
    key = regions_key(regions)
    if capture.evidence.get("regions_key") == key and Path(capture.evidence["overview"]["path"]).exists():
        return capture.evidence
    image = primary_image(capture)
    if image is None:
        raise FileNotFoundError("capture has no decodable image (RAW preview unavailable)")
    out_dir = session_root / "evidence" / capture.id / key
    loop = asyncio.get_running_loop()
    submitted = time.perf_counter()
    started: list[float] = []

    def run():
        started.append(time.perf_counter())
        return build_evidence(
            image, out_dir, regions, overview_long_edge=settings.overview_long_edge,
            crop_max_edge=settings.crop_max_edge, max_crops=settings.max_crops,
            analyze_subjects=settings.subject_analysis,
        )

    ev = await loop.run_in_executor(executor, run)
    ev["timings"]["executor_queue_wait_ms"] = round((started[0] - submitted) * 1000, 2)
    ev["timings"]["total_ms"] = round((time.perf_counter() - submitted) * 1000, 2)
    ev["regions_key"] = key
    ev["image_path"] = str(image)
    return ev
