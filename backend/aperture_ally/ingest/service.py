"""Capture ingestion.

OM Capture owns the camera and writes files into the watch folder; this service only reads them.

* Filesystem notifications are hints. A file is ingested only after its size/mtime are unchanged for
  N consecutive checks *and* it decodes. Truncated files are retried with a bounded timeout, then left
  ``pending_retry`` for the periodic reconciliation scan.
* Completed files are copied (hash-verified, atomic rename, read-only) into session storage. Camera /
  OM Capture originals are never moved, deleted or modified.
* Content hashes dedupe repeated events and re-copied files. RAW/JPEG pairing requires same session,
  source directory and stem *and* matching capture time when both carry it (else close detection
  time). A late RAW attaches to its JPEG capture without triggering new coaching.
* Shot/setup attribution is snapshotted at first detection and persisted, so it survives restart and
  switching the active shot later cannot relabel the capture.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import stat
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import Settings
from ..domain.models import Capture, ProcessingState, Session, ShotRequirement, utcnow
from ..events import EventBus
from ..imaging import raw as rawmod
from ..imaging.evidence import DecodeError, prewarm_overlays, verify_decodable
from ..imaging.metadata import MetadataReader
from ..imaging.pipeline import ensure_evidence
from ..runtime import ContextTracker
from ..telemetry.timing import Timer

log = logging.getLogger(__name__)

DONE = {"ingested", "duplicate", "ignored"}
PENDING = {"discovered", "stabilizing", "pending_retry"}
SKIPPED = "skipped"
IGNORED_SUFFIXES = (".tmp", ".part", ".partial", ".download", ".crdownload")


def is_candidate(path: Path) -> bool:
    name = path.name
    if name.startswith(".") or name.lower().endswith(IGNORED_SUFFIXES):
        return False
    return rawmod.is_raw(path) or rawmod.is_primary_image(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ChangedDuringCopy(Exception):
    pass


def copy_immutable(src: Path, dest_dir: Path, expected_sha: str) -> Path:
    """Copy ``src`` into ``dest_dir`` via temp file + fsync + atomic rename; verify hash; make read-only."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / src.name
    if final.exists():
        if sha256_file(final) == expected_sha:
            return final
        final = dest_dir / f"{src.stem}_{expected_sha[:8]}{src.suffix}"
    tmp = dest_dir / f".{final.name}.incoming"
    h = hashlib.sha256()
    with open(src, "rb") as fin, open(tmp, "wb") as fout:
        for chunk in iter(lambda: fin.read(1 << 20), b""):
            h.update(chunk)
            fout.write(chunk)
        fout.flush()
        os.fsync(fout.fileno())
    if h.hexdigest() != expected_sha:
        tmp.unlink(missing_ok=True)
        raise ChangedDuringCopy(f"{src} changed while copying")
    os.replace(tmp, final)
    os.chmod(final, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return final


@dataclass
class Detection:
    session_id: str
    path: Path
    origin: str
    snapshot: dict[str, Any]
    detected: tuple[int, str]
    auto_coach: bool = True
    quick: bool = False  # manual import of an already complete file
    timings: dict[str, Any] = field(default_factory=dict)  # sub-stage ms + counters → Capture.timings

    async def timed(self, name: str, aw):
        t0 = time.perf_counter()
        try:
            return await aw
        finally:
            self.timings[name] = round(self.timings.get(name, 0) + (time.perf_counter() - t0) * 1000, 2)


@dataclass
class PendingRaw:
    det: Detection
    sha: str
    meta: dict[str, Any]
    future: asyncio.Future = field(repr=False)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


class IngestService:
    def __init__(
        self,
        *,
        store,
        bus: EventBus,
        timer: Timer,
        settings: Settings,
        tracker: ContextTracker,
        executor: Executor,
        metadata: MetadataReader,
        on_ready: Callable[[Capture, bool], Awaitable[None]],
    ):
        self.store = store
        self.bus = bus
        self.timer = timer
        self.settings = settings
        self.tracker = tracker
        self.executor = executor
        # One low-priority worker for work nothing waits on (photo overlays), so it never delays evidence.
        self.background = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bg")
        self.metadata = metadata
        self.on_ready = on_ready
        self._inflight: dict[tuple[str, str], asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._pending_raw: dict[tuple[str, str, str], PendingRaw] = {}
        self._observer = None
        self._reconcile_task: asyncio.Task | None = None
        self.watched_session_id: str | None = None
        self.replay_paths: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    # --- helpers -------------------------------------------------------------------------
    async def _run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self.executor, lambda: fn(*args))

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    def session_root(self, session: Session | str) -> Path:
        sid = session if isinstance(session, str) else session.id
        return self.settings.sessions_dir / sid

    # --- watching ------------------------------------------------------------------------
    async def watch(self, session: Session | None, *, startup: bool = False) -> None:
        """Watch ``session.watch_folder`` (only one session is watched at a time)."""
        await self.stop_watching()
        self._loop = asyncio.get_running_loop()
        if session is None or not session.watch_folder:
            return
        folder = Path(session.watch_folder).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        self.watched_session_id = session.id
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            service = self
            sid = session.id

            class Handler(FileSystemEventHandler):
                def dispatch(self, event):
                    if event.is_directory:
                        return
                    path = getattr(event, "dest_path", None) or event.src_path
                    if event.event_type in ("created", "modified", "moved", "closed"):
                        service._threadsafe_hint(sid, Path(os.fsdecode(path)))

            self._observer = Observer()
            self._observer.schedule(Handler(), str(folder), recursive=self.settings.watch_recursive)
            self._observer.start()
        except Exception as exc:
            log.exception("watchdog failed; relying on reconciliation scans")
            self.bus.publish("ingest.watcher_error", session_id=session.id, error=str(exc))
        await self.recover_pending(session.id)
        await self.reconcile(session, recovered=startup)
        self._reconcile_task = asyncio.create_task(self._reconcile_loop(session.id))
        self.bus.publish("ingest.watching", session_id=session.id, folder=str(folder))

    async def stop_watching(self) -> None:
        if self._reconcile_task:
            self._reconcile_task.cancel()
            self._reconcile_task = None
        if self._observer is not None:
            obs = self._observer
            self._observer = None
            await asyncio.get_running_loop().run_in_executor(None, lambda: (obs.stop(), obs.join(3)))
        self.watched_session_id = None

    def _threadsafe_hint(self, session_id: str, path: Path) -> None:
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self.hint, session_id, path)

    def hint(self, session_id: str, path: Path) -> None:
        if session_id != self.watched_session_id or not is_candidate(path):
            return
        origin = "replay" if str(path) in self.replay_paths else "watch"
        self.schedule(session_id, path, origin)

    async def _reconcile_loop(self, session_id: str) -> None:
        while True:
            await asyncio.sleep(self.settings.reconcile_interval_s)
            try:
                session = await self.store.get(Session, session_id)
                if session:
                    await self.reconcile(session)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("reconcile failed")

    async def reconcile(self, session: Session, *, recovered: bool = False) -> int:
        """Scan the watch folder for files the notifications missed (or created while stopped)."""
        if not session.watch_folder:
            return 0
        folder = Path(session.watch_folder).expanduser()
        if not folder.exists():
            self.bus.publish("ingest.watch_folder_missing", session_id=session.id, folder=str(folder))
            return 0
        since = _parse_iso(session.watch_since).timestamp() - 2 if session.watch_since else 0.0
        it = folder.rglob("*") if self.settings.watch_recursive else folder.glob("*")
        paths = await self._run(lambda: [p for p in it if p.is_file() and is_candidate(p)])
        scheduled = 0
        for p in paths:
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            if st.st_mtime < since:
                continue
            row = await self.store.source_file(session.id, str(p))
            if row and row["status"] in DONE and row["size"] == st.st_size and row["mtime_ns"] == st.st_mtime_ns:
                continue
            if row and row["status"] == SKIPPED:
                continue
            if row and row["status"] == "pending_retry":
                updated = _parse_iso(row["updated_at"])
                if updated and (datetime.now(updated.tzinfo) - updated).total_seconds() < 10:
                    continue
            if (session.id, str(p)) in self._inflight:
                continue
            self.schedule(session.id, p, "recovered" if recovered else "watch", recovered=recovered)
            scheduled += 1
        return scheduled

    async def recover_pending(self, session_id: str) -> None:
        """Captures interrupted mid-analysis at shutdown become retryable, and are never spoken."""
        for cap in await self.store.captures(session_id):
            if cap.processing_state in (ProcessingState.analyzing,):
                cap.processing_state = ProcessingState.pending_retry
                cap.error = "analysis interrupted by restart; request review to retry"
                await self.store.put(cap)

    # --- scheduling ----------------------------------------------------------------------
    def schedule(
        self,
        session_id: str,
        path: Path,
        origin: str,
        *,
        shot_id: str | None = None,
        recovered: bool = False,
        auto_coach: bool = True,
        quick: bool = False,
    ) -> asyncio.Task:
        key = (session_id, str(path))
        if key in self._inflight:
            return self._inflight[key]
        ctx = self.tracker.get(session_id)
        now_mono = time.monotonic()
        ambiguous = bool(ctx.shot_changed_mono) and (now_mono - ctx.shot_changed_mono) < self.settings.attribution_ambiguity_s
        snapshot = {
            "shot_id": shot_id if shot_id is not None else ctx.active_shot_id,
            "setup_revision_id": ctx.setup_revision_id,
            "detected_at": utcnow(),
            "ambiguous": (ambiguous or recovered) and shot_id is None,
            "recovered": recovered,
            "user_reported_change": None,
        }
        if snapshot["ambiguous"] and ambiguous:
            snapshot["previous_shot_id"] = ctx.previous_shot_id
            snapshot["seconds_after_switch"] = round(now_mono - ctx.shot_changed_mono, 2)
        if not recovered and snapshot["shot_id"] == ctx.active_shot_id and is_candidate(path) and not rawmod.is_raw(path):
            snapshot["user_reported_change"], ctx.pending_change = ctx.pending_change, None
        det = Detection(session_id, path, origin, snapshot, Timer.now(), auto_coach=auto_coach and not recovered,
                        quick=quick)
        task = asyncio.create_task(self._process(det))
        self._inflight[key] = task
        task.add_done_callback(lambda _t: self._inflight.pop(key, None))
        return task

    async def drain(self, timeout: float = 30.0) -> None:
        """Wait for in-flight ingests (tests / replay)."""
        deadline = time.monotonic() + timeout
        while self._inflight and time.monotonic() < deadline:
            await asyncio.gather(*list(self._inflight.values()), return_exceptions=True)

    # --- processing ----------------------------------------------------------------------
    async def _process(self, det: Detection) -> str | None:
        path, sid = det.path, det.session_id
        try:
            st = path.stat()
        except FileNotFoundError:
            return None
        row = await self.store.source_file(sid, str(path))
        if row and row["status"] in DONE and row["size"] == st.st_size and row["mtime_ns"] == st.st_mtime_ns:
            return row["capture_id"]
        if row and row["status"] == SKIPPED:
            return None
        if row and row["status"] in PENDING | {"failed"} and row["snapshot"]:
            det.snapshot = {**row["snapshot"], "recovered": det.snapshot["recovered"] or row["snapshot"].get("recovered")}
            if det.snapshot["recovered"]:
                det.auto_coach = False
        kind = "raw" if rawmod.is_raw(path) else "jpeg"
        await self.store.record_source(sid, str(path), size=st.st_size, mtime_ns=st.st_mtime_ns, kind=kind,
                                       status="stabilizing", snapshot=det.snapshot)
        self.bus.publish("capture.discovered", session_id=sid, path=path.name, shot_id=det.snapshot["shot_id"])

        det.timings["file_age_at_first_stat_ms"] = round((time.time() - st.st_mtime) * 1000, 1)
        stats: dict[str, int] = {}
        stable = await det.timed("stability_wait_ms", self._wait_stable(path, kind, quick=det.quick, stats=stats))
        det.timings.update({f"stability_{k}": v for k, v in stats.items()})
        if stable is None:
            st2 = path.stat() if path.exists() else st
            await self.store.record_source(sid, str(path), size=st2.st_size, mtime_ns=st2.st_mtime_ns, kind=kind,
                                           status="pending_retry", note="not stable/decodable before timeout")
            self.bus.publish("capture.pending_retry", session_id=sid, path=path.name)
            return None
        size, mtime_ns = stable
        det.timings["source_bytes"] = stable[0]
        sha = await det.timed("hash_ms", self._run(sha256_file, path))
        dup = await self.store.source_by_hash(sid, sha)
        if dup:
            status = "ingested" if dup["source_path"] == str(path) else "duplicate"
            await self.store.record_source(sid, str(path), size=size, mtime_ns=mtime_ns, kind=kind, status=status,
                                           sha256=sha, capture_id=dup["capture_id"], note=f"same content as {dup['source_path']}")
            if status == "duplicate":
                self.bus.publish("capture.duplicate", session_id=sid, capture_id=dup["capture_id"], path=path.name)
            return dup["capture_id"]
        try:
            if kind == "raw":
                return await self._ingest_raw(det, sha, size, mtime_ns)
            return await self._ingest_primary(det, sha, size, mtime_ns)
        except ChangedDuringCopy as exc:
            await self.store.record_source(sid, str(path), size=size, mtime_ns=mtime_ns, kind=kind,
                                           status="pending_retry", note=str(exc))
            return None
        except Exception as exc:
            log.exception("ingest failed for %s", path)
            await self.store.record_source(sid, str(path), size=size, mtime_ns=mtime_ns, kind=kind, status="failed",
                                           sha256=sha, note=str(exc))
            self.bus.publish("capture.ingest_failed", session_id=sid, path=path.name, error=str(exc))
            return None

    async def _wait_stable(self, path: Path, kind: str, *, quick: bool = False,
                           stats: dict[str, int] | None = None) -> tuple[int, int] | None:
        stats = stats if stats is not None else {}
        stats.setdefault("polls", 0)
        stats.setdefault("size_changes", 0)
        stats.setdefault("decode_failures", 0)
        interval = self.settings.stability_interval_ms / 1000
        needed = 1 if quick else self.settings.stability_checks
        raw_settle = max(1, round(self.settings.raw_unverified_settle_s / interval))
        deadline = time.monotonic() + self.settings.stability_timeout_s
        prev: tuple[int, int] | None = None
        count = 0
        while time.monotonic() < deadline:
            try:
                st = path.stat()
            except FileNotFoundError:
                return None
            cur = (st.st_size, st.st_mtime_ns)
            stats["polls"] += 1
            if prev is not None and cur != prev:
                stats["size_changes"] += 1
            if st.st_size > 0 and (quick or cur == prev):
                count += 1
            else:
                count = 0
            prev = cur
            if count >= needed:
                if await self._decodes(path, kind):
                    return cur
                stats["decode_failures"] += 1
                if kind == "raw" and count >= needed + raw_settle:
                    # LibRaw can't tell "truncated" from "unsupported". An undecodable RAW whose size has
                    # been stable for an extra settle period is kept (original preserved) but flagged
                    # later as preview-unavailable; the JPEG/manual-import path keeps the app usable.
                    return cur
                if kind != "raw":
                    count = 0
            await asyncio.sleep(interval)
        return None

    async def _decodes(self, path: Path, kind: str) -> bool:
        try:
            if kind == "raw":
                if rawmod.rawpy_available():
                    await self._run(rawmod.verify_raw, path)
            else:
                await self._run(verify_decodable, path)
            return True
        except (DecodeError, rawmod.RawUnsupported):
            return False

    # --- pairing -------------------------------------------------------------------------
    def _time_match(self, a_meta: dict, b_meta: dict, a_det: tuple[int, str] | None,
                    b_det: tuple[int, str] | None) -> tuple[bool, dict[str, Any]]:
        ta, tb = _parse_iso(a_meta.get("datetime_original")), _parse_iso(b_meta.get("datetime_original"))
        if ta and tb:
            delta = abs((ta - tb).total_seconds())
            return delta <= self.settings.pair_time_tolerance_s, {"method": "stem+dir+exif_time", "delta_s": delta}
        if a_det and b_det:
            delta = abs(a_det[0] - b_det[0]) / 1e9
            return delta <= 30, {"method": "stem+dir+detection_time", "delta_s": round(delta, 3)}
        return False, {"method": "stem+dir", "reason": "no timestamps to confirm pairing"}

    async def _find_capture(self, sid: str, det: Detection, want: str) -> Capture | None:
        """Existing capture with same dir/stem missing the ``want`` ('raw' or 'jpeg') component."""
        for cap in reversed(await self.store.captures(sid)):
            p = cap.pairing
            if p.get("dir") != str(det.path.parent) or p.get("stem") != det.path.stem:
                continue
            if want == "raw" and cap.jpeg_path and not cap.raw_path:
                return cap
            if want == "jpeg" and cap.raw_path and not cap.jpeg_path:
                return cap
        return None

    async def _ingest_primary(self, det: Detection, sha: str, size: int, mtime_ns: int) -> str:
        sid, path = det.session_id, det.path
        meta = await det.timed("metadata_ms", self._run(self.metadata.read, path, True))
        root = self.session_root(sid)
        async with self._lock(sid):
            late_for = await self._find_capture(sid, det, "jpeg")
            if late_for:
                ok, ev = self._time_match(meta, late_for.exif, None, None)
                if ok or ev["method"] == "stem+dir":
                    stored = await self._run(copy_immutable, path, root / "originals" / late_for.id, sha)
                    late_for.jpeg_path, late_for.jpeg_sha256 = str(stored), sha
                    late_for.preview_source = "jpeg"
                    late_for.source_paths.append(str(path))
                    late_for.pairing = {**late_for.pairing, "late_jpeg": True, "jpeg_pairing": ev}
                    raw_tags = meta.pop("_raw", None)
                    late_for.exif = meta or late_for.exif
                    late_for.exif_raw = raw_tags or late_for.exif_raw
                    await self.store.put(late_for)
                    await self.store.record_source(sid, str(path), size=size, mtime_ns=mtime_ns, kind="jpeg",
                                                   status="ingested", sha256=sha, capture_id=late_for.id)
                    self.bus.publish("capture.updated", session_id=sid, capture_id=late_for.id, late_jpeg=True)
                    await self._refresh_evidence(late_for)
                    return late_for.id

            key = (sid, str(path.parent), path.stem)
            partner = self._pending_raw.get(key)
            pair_ev: dict[str, Any] | None = None
            if partner:
                ok, pair_ev = self._time_match(meta, partner.meta, det.detected, partner.det.detected)
                if ok:
                    self._pending_raw.pop(key)
                else:
                    partner = None

            cap = self._new_capture(det, meta)
            cap.pairing = {"dir": str(path.parent), "stem": path.stem}
            stored = await det.timed("copy_ms", self._run(copy_immutable, path, root / "originals" / cap.id, sha))
            cap.jpeg_path, cap.jpeg_sha256, cap.preview_source = str(stored), sha, "jpeg"
            if partner:
                raw_stored = await det.timed("raw_copy_ms", self._run(
                    copy_immutable, partner.det.path, root / "originals" / cap.id, partner.sha))
                cap.timings["raw_partner"] = partner.det.timings
                cap.raw_path, cap.raw_sha256 = str(raw_stored), partner.sha
                cap.source_paths.append(str(partner.det.path))
                cap.pairing["raw_pairing"] = pair_ev
            cap = await self.store.insert_capture(cap)
            await self.store.record_source(sid, str(path), size=size, mtime_ns=mtime_ns, kind="jpeg",
                                           status="ingested", sha256=sha, capture_id=cap.id)
            if partner:
                pst = partner.det.path.stat()
                await self.store.record_source(sid, str(partner.det.path), size=pst.st_size, mtime_ns=pst.st_mtime_ns,
                                               kind="raw", status="ingested", sha256=partner.sha, capture_id=cap.id)
                if not partner.future.done():
                    partner.future.set_result(cap.id)
        await self._capture_ready(cap, det)
        return cap.id

    async def _ingest_raw(self, det: Detection, sha: str, size: int, mtime_ns: int) -> str | None:
        sid, path = det.session_id, det.path
        meta = await det.timed("metadata_ms", self._run(self.metadata.read, path, True))
        root = self.session_root(sid)
        async with self._lock(sid):
            jpeg_cap = await self._find_capture(sid, det, "raw")
            if jpeg_cap:
                ok, ev = self._time_match(meta, jpeg_cap.exif, None, None)
                if ok or ev["method"] == "stem+dir":
                    # Late RAW: attach to existing JPEG capture; never triggers duplicate coaching.
                    stored = await self._run(copy_immutable, path, root / "originals" / jpeg_cap.id, sha)
                    jpeg_cap.raw_path, jpeg_cap.raw_sha256 = str(stored), sha
                    jpeg_cap.source_paths.append(str(path))
                    jpeg_cap.pairing = {**jpeg_cap.pairing, "late_raw": True, "raw_pairing": ev}
                    await self.store.put(jpeg_cap)
                    await self.store.record_source(sid, str(path), size=size, mtime_ns=mtime_ns, kind="raw",
                                                   status="ingested", sha256=sha, capture_id=jpeg_cap.id)
                    self.bus.publish("capture.updated", session_id=sid, capture_id=jpeg_cap.id, late_raw=True)
                    return jpeg_cap.id
            key = (sid, str(path.parent), path.stem)
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            pending = PendingRaw(det, sha, meta, fut)
            self._pending_raw[key] = pending
        try:
            return await det.timed("pair_wait_ms", asyncio.wait_for(asyncio.shield(fut), self.settings.pair_grace_s))
        except TimeoutError:
            pass
        async with self._lock(sid):
            if fut.done():
                return fut.result()
            if self._pending_raw.get(key) is pending:
                self._pending_raw.pop(key)
            cap = self._new_capture(det, meta)
            cap.pairing = {"dir": str(path.parent), "stem": path.stem, "raw_only": True}
            stored = await det.timed("copy_ms", self._run(copy_immutable, path, root / "originals" / cap.id, sha))
            cap.raw_path, cap.raw_sha256 = str(stored), sha
            preview = root / "evidence" / cap.id / "raw_preview.jpg"
            try:
                cap.preview_source = await det.timed("raw_preview_ms", self._run(rawmod.make_preview, stored, preview))
                cap.pairing["raw_preview_path"] = str(preview)
            except rawmod.RawUnsupported as exc:
                cap.preview_source = "none"
                cap.processing_state = ProcessingState.failed
                cap.error = f"RAW preview unavailable ({exc}); shoot RAW+JPEG or import a JPEG"
            cap.timings = dict(det.timings)
            cap = await self.store.insert_capture(cap)
            await self.store.record_source(sid, str(path), size=size, mtime_ns=mtime_ns, kind="raw",
                                           status="ingested", sha256=sha, capture_id=cap.id)
        if cap.processing_state == ProcessingState.failed:
            self.bus.publish("capture.failed", session_id=sid, capture_id=cap.id, error=cap.error)
            return cap.id
        await self._capture_ready(cap, det)
        return cap.id

    def _new_capture(self, det: Detection, meta: dict[str, Any]) -> Capture:
        snap = det.snapshot
        raw_tags = meta.pop("_raw", {})
        return Capture(
            exif_raw=raw_tags,
            session_id=det.session_id,
            shot_id=snap.get("shot_id"),
            setup_revision_id=snap.get("setup_revision_id"),
            origin=det.origin,  # type: ignore[arg-type]
            recovered=bool(snap.get("recovered")),
            attribution_ambiguous=bool(snap.get("ambiguous")),
            source_paths=[str(det.path)],
            exif=meta,
            capture_time=meta.get("datetime_original"),
            user_reported_change=snap.get("user_reported_change"),
            detected_at=snap.get("detected_at") or utcnow(),
            attribution_context={k: snap[k] for k in ("previous_shot_id", "seconds_after_switch") if k in snap},
        )

    # --- readiness + evidence --------------------------------------------------------------
    async def _capture_ready(self, cap: Capture, det: Detection) -> None:
        cap.timings = {**cap.timings, **det.timings}
        cap.processing_state = ProcessingState.ready
        cap.ready_at = utcnow()
        await self.store.put(cap)
        await self.timer.mark("file_detected", at=det.detected, session_id=cap.session_id, capture_id=cap.id)
        await self.timer.mark("file_ready", session_id=cap.session_id, capture_id=cap.id)
        self.tracker.capture_ready(cap.session_id, cap.shot_id, cap.id, cap.seq)
        self.bus.publish("capture.ready", session_id=cap.session_id, capture_id=cap.id, seq=cap.seq,
                         shot_id=cap.shot_id, recovered=cap.recovered, ambiguous=cap.attribution_ambiguous)
        ok = await self._refresh_evidence(cap)
        if ok:
            ready = await self.store.get(Capture, cap.id)
            await self.on_ready(ready, det.auto_coach)
            if ready:
                self._prewarm_overlays(ready)

    def _prewarm_overlays(self, cap: Capture) -> None:
        """Lost-detail overlay + zone masks in the background, after coaching has been handed the photo."""
        ev = cap.evidence or {}
        if not (ev.get("clip_overlay") and ev.get("image_path") and ev.get("overview")):
            return
        image, overview, out = Path(ev["image_path"]), ev["overview"], Path(ev["clip_overlay"])

        def run() -> None:
            try:
                prewarm_overlays(image, overview, out)
            except Exception:
                log.exception("overlay prewarm failed for %s", cap.id)  # on-demand generation still works

        self.background.submit(run)

    async def _refresh_evidence(self, cap: Capture) -> bool:
        shot = await self.store.get(ShotRequirement, cap.shot_id) if cap.shot_id else None
        regions = shot.sharp_regions if shot else []
        try:
            ev = await ensure_evidence(cap, regions, self.session_root(cap.session_id), self.settings, self.executor)
        except Exception as exc:
            log.exception("evidence failed")
            msg = f"evidence failed: {exc}"

            def fail(c: Capture) -> None:
                c.processing_state = ProcessingState.failed
                c.error = msg

            await self.store.update(Capture, cap.id, fail)
            self.bus.publish("capture.failed", session_id=cap.session_id, capture_id=cap.id, error=str(exc))
            return False

        def apply(c: Capture) -> None:
            c.evidence = ev
            c.timings["evidence"] = ev.get("timings", {})
            c.width, c.height = ev["width"], ev["height"]

        await self.store.update(Capture, cap.id, apply)
        await self.timer.mark("evidence_ready", session_id=cap.session_id, capture_id=cap.id)
        self.bus.publish("capture.evidence_ready", session_id=cap.session_id, capture_id=cap.id)
        return True

    # --- manual import -------------------------------------------------------------------
    def check_import_path(self, path: Path, extra_roots: list[Path] | None = None) -> Path:
        resolved = path.expanduser().resolve()
        roots = [r.expanduser().resolve() for r in [*self.settings.import_roots, *(extra_roots or [])]]
        if not any(resolved.is_relative_to(r) for r in roots):
            raise PermissionError(f"{path} is outside configured import roots")
        return resolved

    async def import_paths(self, session_id: str, paths: list[Path], *, origin: str = "import",
                           shot_id: str | None = None, auto_coach: bool = False,
                           extra_roots: list[Path] | None = None) -> list[str | None]:
        files: list[Path] = []
        for p in paths:
            rp = self.check_import_path(p, extra_roots)
            if rp.is_dir():
                files.extend(sorted(f for f in rp.iterdir() if f.is_file() and is_candidate(f)))
            elif is_candidate(rp):
                files.append(rp)
        # Primary images first so RAW partners pair without waiting for the grace period.
        files.sort(key=lambda f: (rawmod.is_raw(f), f.name))
        tasks = [self.schedule(session_id, f, origin, shot_id=shot_id, auto_coach=auto_coach, quick=True)
                 for f in files]
        return list(await asyncio.gather(*tasks))

    def save_upload(self, session_id: str, filename: str, data: bytes) -> Path:
        name = Path(filename).name
        if not is_candidate(Path(name)):
            raise ValueError(f"unsupported file type: {name}")
        folder = self.session_root(session_id) / "uploads" / hashlib.sha256(data).hexdigest()[:12]
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / name
        dest.write_bytes(data)
        return dest

    # --- user actions on stuck files --------------------------------------------------------
    async def _source_row(self, session_id: str, key: str) -> dict | None:
        try:
            return await self.store.source_file_by_id(session_id, int(key))
        except ValueError:
            return None

    async def retry_source(self, session: Session, key: str) -> dict | None:
        """Read a pending/failed file again now, skipping the reconcile backoff. None = unknown key."""
        row = await self._source_row(session.id, key)
        if row is None:
            return None
        if row["status"] not in PENDING | {"failed"}:
            raise ValueError(f"file is {row['status']}, not waiting to be read")
        path = Path(row["source_path"])
        if not path.exists():
            raise FileNotFoundError(f"{path.name} is no longer in the folder")
        if (session.id, str(path)) not in self._inflight:
            watched = session.watch_folder and path.resolve().is_relative_to(Path(session.watch_folder).expanduser().resolve())
            origin = "replay" if str(path) in self.replay_paths else "watch" if watched else "import"
            self.schedule(session.id, path, origin)
        self.bus.publish("ingest.retry_requested", session_id=session.id, path=path.name, status=row["status"])
        return row

    async def skip_source(self, session_id: str, key: str) -> dict | None:
        """Stop trying to read a file: recorded as skipped, never retried, gone from the pending list."""
        row = await self._source_row(session_id, key)
        if row is None:
            return None
        if row["status"] not in PENDING | {"failed"}:
            raise ValueError(f"file is {row['status']}, not waiting to be read")
        task = self._inflight.pop((session_id, row["source_path"]), None)
        if task:
            task.cancel()
        await self.store.set_source_status(row["id"], SKIPPED, f"skipped by user (was {row['status']})")
        self.bus.publish("ingest.skipped", session_id=session_id, path=Path(row["source_path"]).name,
                         previous_status=row["status"], note=row["note"])
        return row

    async def reread_capture(self, cap: Capture) -> tuple[bool, str | None]:
        """Decode a capture's stored file again (after a bad read) and rebuild its evidence."""
        if cap.raw_path and not cap.jpeg_path and cap.preview_source in (None, "none"):
            preview = self.session_root(cap.session_id) / "evidence" / cap.id / "raw_preview.jpg"
            try:
                source = await self._run(rawmod.make_preview, Path(cap.raw_path), preview)
            except rawmod.RawUnsupported as exc:
                msg = f"RAW preview unavailable ({exc}); shoot RAW+JPEG or import a JPEG"

                def still_failed(c: Capture) -> None:
                    c.error = msg

                await self.store.update(Capture, cap.id, still_failed)
                return False, msg

            def set_preview(c: Capture) -> None:
                c.preview_source = source
                c.pairing = {**c.pairing, "raw_preview_path": str(preview)}

            cap = await self.store.update(Capture, cap.id, set_preview) or cap
        if not await self._refresh_evidence(cap):
            fresh = await self.store.get(Capture, cap.id)
            return False, fresh.error if fresh else "evidence failed"

        def ready(c: Capture) -> None:
            c.processing_state = ProcessingState.ready
            c.error = None
            c.ready_at = c.ready_at or utcnow()

        cap = await self.store.update(Capture, cap.id, ready) or cap
        self.tracker.capture_ready(cap.session_id, cap.shot_id, cap.id, cap.seq)
        self.bus.publish("capture.updated", session_id=cap.session_id, capture_id=cap.id, reread=True)
        return True, None

    async def reattach_evidence(self, capture: Capture) -> bool:
        return await self._refresh_evidence(capture)

    async def close(self) -> None:
        await self.stop_watching()
        self.background.shutdown(wait=False, cancel_futures=True)
        for t in list(self._inflight.values()):
            t.cancel()
