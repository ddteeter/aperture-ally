"""Optimisation telemetry: provider-call recording, persisted events, network probes, file logging.

Everything here is local (SQLite + ``<data_dir>/logs``) and git-ignored. Stored model I/O contains the
shot context, notes and model output, never image bytes (evidence files are referenced by path).
Disable model I/O capture with ``APERTURE_ALLY_STORE_MODEL_IO=false``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import logging.handlers
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ..domain.models import ModelCall, utcnow
from .timing import BOOT_ID

log = logging.getLogger(__name__)
events_log = logging.getLogger("aperture_ally.events")

PROVIDER_HOSTS = {"openai": "api.openai.com", "gemini": "generativelanguage.googleapis.com",
                  "claude": "api.anthropic.com"}


# --- file logging ---------------------------------------------------------------------------
_FILE_HANDLER_TAG = "aperture_ally_file"


def setup_file_logging(data_dir: Path, level: int = logging.INFO) -> Path:
    """Rotating text log (10 MB × 5) shared by the app and uvicorn. Idempotent."""
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / "aperture-ally.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(threadName)s]: %(message)s")
    for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if any(getattr(h, "name", None) == _FILE_HANDLER_TAG and getattr(h, "baseFilename", None) == str(path)
               for h in logger.handlers):
            continue
        for h in list(logger.handlers):  # replace a handler for a previous data dir (tests)
            if getattr(h, "name", None) == _FILE_HANDLER_TAG:
                logger.removeHandler(h)
                h.close()
        h = logging.handlers.RotatingFileHandler(path, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
        h.name = _FILE_HANDLER_TAG
        h.setFormatter(fmt)
        h.setLevel(level)
        logger.addHandler(h)
    logging.getLogger().setLevel(min(logging.getLogger().level or level, level))
    return path


# --- persisted event stream -----------------------------------------------------------------
class TelemetrySink:
    """Persists every EventBus event (and explicit telemetry) to ``telemetry_events``."""

    SKIP = {"ping", "hello"}

    def __init__(self, store):
        self.store = store  # AsyncStore
        self._tasks: set[asyncio.Task] = set()

    def __call__(self, event: dict[str, Any]) -> None:
        if event["type"] in self.SKIP:
            return
        self.record(event["type"], event.get("payload") or {}, session_id=event.get("session_id"),
                    capture_id=event.get("capture_id"), wall=event.get("ts"))

    def record(self, kind: str, data: dict[str, Any] | None = None, *, session_id: str | None = None,
               capture_id: str | None = None, wall: str | None = None) -> None:
        events_log.info("%s session=%s capture=%s %s", kind, (session_id or "-")[:8], (capture_id or "-")[:8],
                        json.dumps(data, default=str)[:400] if data else "")
        args = (kind, wall or utcnow(), time.monotonic_ns(), BOOT_ID, data)
        kw = {"session_id": session_id, "capture_id": capture_id}
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.store.sync.add_telemetry(*args, **kw)
            return
        # Single DB thread preserves submission order; keep references until done.
        t = loop.create_task(self.store.add_telemetry(*args, **kw))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def flush(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


def startup_snapshot(settings, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    import importlib.metadata as md

    versions = {}
    for pkg in ("fastapi", "openai", "google-genai", "opencv-python-headless", "pillow", "rawpy", "numpy",
                "watchdog", "sounddevice", "pynput"):
        try:
            versions[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            versions[pkg] = None
    return {
        "boot_id": BOOT_ID,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "exiftool": shutil.which("exiftool") is not None,
        "versions": versions,
        "config": settings.public_view(),
        **(extra or {}),
    }


# --- network --------------------------------------------------------------------------------
def default_interface() -> dict[str, Any]:
    """Best-effort: which interface carries the default route (macOS / Linux). No SSIDs recorded."""
    info: dict[str, Any] = {}
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["route", "-n", "get", "default"], capture_output=True, text=True, timeout=2,
                                 check=False).stdout
            m = re.search(r"interface:\s*(\S+)", out)
            if m:
                info["interface"] = m.group(1)
                ports = subprocess.run(["networksetup", "-listallhardwareports"], capture_output=True, text=True,
                                       timeout=3, check=False).stdout
                for block in ports.split("\n\n"):
                    if f"Device: {info['interface']}" in block:
                        pm = re.search(r"Hardware Port:\s*(.+)", block)
                        info["hardware_port"] = pm.group(1).strip() if pm else None
        elif shutil.which("ip"):
            out = subprocess.run(["ip", "route", "get", "1.1.1.1"], capture_output=True, text=True, timeout=2,
                                 check=False).stdout
            m = re.search(r"dev\s+(\S+)", out)
            if m:
                info["interface"] = m.group(1)
    except Exception as exc:
        info["error"] = str(exc)
    return info


async def probe_host(host: str, port: int = 443, timeout: float = 5.0) -> dict[str, Any]:
    """DNS + TCP connect time to a provider endpoint (no TLS, no request, no credentials)."""
    loop = asyncio.get_running_loop()
    res: dict[str, Any] = {"host": host}
    t0 = time.monotonic()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(host, port, type=1), timeout)
        res["dns_ms"] = round((time.monotonic() - t0) * 1000, 1)
        t1 = time.monotonic()
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        res["tcp_connect_ms"] = round((time.monotonic() - t1) * 1000, 1)
        res["addresses"] = len(infos)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        res["ok"] = True
    except Exception as exc:
        res["ok"] = False
        res["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return res


class NetworkMonitor:
    """Periodic probes of the configured providers' endpoints; last result attached to each model call."""

    def __init__(self, settings, sink: TelemetrySink, hosts: Callable[[], list[str]]):
        self.settings = settings
        self.sink = sink
        self.hosts = hosts
        self.last: dict[str, Any] | None = None
        self._task: asyncio.Task | None = None
        self._busy = False

    def start(self) -> None:
        if self.settings.network_probe_interval_s > 0 and self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self.probe("periodic")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("network probe failed")
            await asyncio.sleep(self.settings.network_probe_interval_s)

    async def probe(self, reason: str) -> dict[str, Any] | None:
        hosts = self.hosts()
        if not hosts or self._busy:
            return self.last
        self._busy = True
        try:
            iface = await asyncio.get_running_loop().run_in_executor(None, default_interface)
            results = await asyncio.gather(*(probe_host(h) for h in hosts))
            self.last = {"at": utcnow(), "reason": reason, "interface": iface, "probes": list(results)}
            self.sink.record("network.probe", self.last)
            return self.last
        finally:
            self._busy = False

    def trigger(self, reason: str) -> None:
        """Probe soon (e.g. right after a provider failure) without blocking the caller."""
        if self.hosts():
            t = asyncio.create_task(self.probe(reason))
            self.sink._tasks.add(t)
            t.add_done_callback(self.sink._tasks.discard)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None


# --- provider call recording ----------------------------------------------------------------
def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def describe_images(images) -> list[dict[str, Any]]:
    from PIL import Image

    out = []
    for im in images:
        d = {"role": im.role, "kind": im.kind, "region_id": im.region_id, "label": im.label, "path": im.path}
        try:
            p = Path(im.path)
            d["bytes"] = p.stat().st_size
            with Image.open(p) as f:
                d["width"], d["height"] = f.size
        except Exception as exc:
            d["error"] = str(exc)
        out.append(d)
    return out


def describe_request(req, provider) -> dict[str, Any]:
    """What was sent, minus image bytes: full context/instructions, image sizes, provider options."""
    images = describe_images(req.images)
    return {
        "purpose": req.purpose,
        "schema_name": req.schema_name,
        "schema_sha": _sha(repr(req.schema)),
        "instructions_sha": _sha(req.instructions),
        "instructions": req.instructions,
        "context": req.context,
        "context_chars": len(req.context_text()),
        "images": images,
        "image_count": len(images),
        "image_bytes_total": sum(i.get("bytes", 0) for i in images),
        "provider_options": {k: getattr(provider, k) for k in ("image_detail", "media_resolution",
                                                              "max_output_tokens", "timeout_s")
                             if hasattr(provider, k)},
    }


class ModelCallRecorder:
    def __init__(self, store, settings, network: NetworkMonitor | None, sink: TelemetrySink):
        self.store = store
        self.settings = settings
        self.network = network
        self.sink = sink

    async def call(self, fn: Callable[[], Awaitable[Any]], *, purpose: str, attempt: int, provider: Any,
                   req=None, request_extra: dict[str, Any] | None = None, queue_wait_ms: float | None = None,
                   timeout_s: float | None = None, collect: list[str] | None = None,
                   **ids: Any) -> tuple[Any, ModelCall]:
        """Run ``fn`` (a provider call), persist a ModelCall whatever happens; re-raise on failure."""
        from ..coaching.providers.base import ProviderUnavailable

        rec = ModelCall(purpose=purpose, attempt=attempt, provider=getattr(provider, "name", str(provider)),  # type: ignore[arg-type]
                        model_requested=getattr(provider, "model", None),
                        prompt_version=getattr(req, "prompt_version", None), queue_wait_ms=queue_wait_ms,
                        boot_id=BOOT_ID, network=self.network.last if self.network else None, **ids)
        if collect is not None:
            collect.append(rec.id)
        if self.settings.store_model_io:
            rec.request = {**(describe_request(req, provider) if req is not None else {}), **(request_extra or {})}
        t0 = time.monotonic()
        try:
            coro = fn()
            resp = await (asyncio.wait_for(coro, timeout_s) if timeout_s else coro)
        except asyncio.CancelledError:
            rec.status, rec.latency_ms = "cancelled", (time.monotonic() - t0) * 1000
            await self.store.put(rec)
            raise
        except BaseException as exc:
            rec.latency_ms = (time.monotonic() - t0) * 1000
            rec.status = ("timeout" if isinstance(exc, TimeoutError)
                          else "unavailable" if isinstance(exc, ProviderUnavailable) else "error")
            rec.error = f"{type(exc).__name__}: {exc}"[:2000]
            await self.store.put(rec)
            if self.network and rec.status in ("timeout", "unavailable"):
                self.network.trigger(f"{rec.provider} {rec.status}")
            raise
        rec.latency_ms = (time.monotonic() - t0) * 1000
        text = getattr(resp, "text", resp if isinstance(resp, str) else None)
        if self.settings.store_model_io:
            rec.response_text = text
        rec.model_resolved = getattr(resp, "model_resolved", None) or rec.model_requested
        rec.response_id = getattr(resp, "response_id", None)
        rec.usage = dict(getattr(resp, "usage", {}) or {})
        await self.store.put(rec)
        return resp, rec

    async def mark(self, rec: ModelCall, status: str, errors: list[str] | None = None,
                   warnings: list[str] | None = None) -> None:
        rec.status = status  # type: ignore[assignment]
        rec.validation_errors = errors or []
        rec.warnings = warnings or []
        await self.store.put(rec)
