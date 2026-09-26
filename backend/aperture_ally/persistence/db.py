"""SQLite persistence.

Each record table keeps a few indexed columns for querying plus a JSON ``data`` body validated by the
Pydantic record on read. Schema changes are appended to ``MIGRATIONS``; ``PRAGMA user_version`` tracks
what has been applied. ``Store`` is synchronous and thread-safe; ``AsyncStore`` runs every call on a
single dedicated DB thread so the event loop never blocks and writes stay ordered.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from ..domain.models import (
    Assessment,
    Capture,
    Experiment,
    KeeperDecision,
    Session,
    SetupRevision,
    ShotRequirement,
    VoiceTurn,
    utcnow,
)

T = TypeVar("T", bound=BaseModel)

MIGRATIONS: list[str] = [
    # v1 — initial schema
    """
    CREATE TABLE sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, data TEXT NOT NULL);
    CREATE TABLE setup_revisions (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), revision INTEGER NOT NULL,
        data TEXT NOT NULL, UNIQUE(session_id, revision));
    CREATE TABLE shots (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), ordinal INTEGER NOT NULL,
        data TEXT NOT NULL);
    CREATE TABLE captures (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), seq INTEGER NOT NULL,
        shot_id TEXT, processing_state TEXT NOT NULL, jpeg_sha256 TEXT, raw_sha256 TEXT, data TEXT NOT NULL,
        UNIQUE(session_id, seq));
    CREATE INDEX captures_shot ON captures(session_id, shot_id);
    CREATE TABLE source_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, source_path TEXT NOT NULL,
        size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, sha256 TEXT, kind TEXT NOT NULL,
        capture_id TEXT, status TEXT NOT NULL, first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        snapshot TEXT, note TEXT, UNIQUE(session_id, source_path));
    CREATE INDEX source_files_hash ON source_files(session_id, sha256);
    CREATE TABLE assessments (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, capture_id TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, data TEXT NOT NULL);
    CREATE INDEX assessments_capture ON assessments(capture_id);
    CREATE TABLE experiments (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, baseline_capture_id TEXT NOT NULL,
        follow_up_capture_id TEXT, data TEXT NOT NULL);
    CREATE TABLE keeper_decisions (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, shot_id TEXT NOT NULL, capture_id TEXT NOT NULL,
        revoked_at TEXT, data TEXT NOT NULL);
    CREATE TABLE voice_turns (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, started_at TEXT NOT NULL, data TEXT NOT NULL);
    CREATE TABLE timing_marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, capture_id TEXT, assessment_id TEXT,
        voice_turn_id TEXT, stage TEXT NOT NULL, wall TEXT NOT NULL, mono_ns INTEGER NOT NULL,
        boot_id TEXT NOT NULL, extra TEXT);
    CREATE INDEX timing_capture ON timing_marks(capture_id);
    """,
]

_TABLES: dict[type[BaseModel], str] = {
    Session: "sessions",
    SetupRevision: "setup_revisions",
    ShotRequirement: "shots",
    Capture: "captures",
    Assessment: "assessments",
    Experiment: "experiments",
    KeeperDecision: "keeper_decisions",
    VoiceTurn: "voice_turns",
}


def _columns(obj: BaseModel) -> dict[str, Any]:
    d = obj.__dict__
    match obj:
        case Session():
            return {"created_at": d["created_at"]}
        case SetupRevision():
            return {"session_id": d["session_id"], "revision": d["revision"]}
        case ShotRequirement():
            return {"session_id": d["session_id"], "ordinal": d["ordinal"]}
        case Capture():
            return {
                "session_id": d["session_id"], "seq": d["seq"], "shot_id": d["shot_id"],
                "processing_state": str(d["processing_state"]), "jpeg_sha256": d["jpeg_sha256"],
                "raw_sha256": d["raw_sha256"],
            }
        case Assessment():
            return {"session_id": d["session_id"], "capture_id": d["capture_id"], "status": d["status"],
                    "created_at": d["created_at"]}
        case Experiment():
            return {"session_id": d["session_id"], "baseline_capture_id": d["baseline_capture_id"],
                    "follow_up_capture_id": d["follow_up_capture_id"]}
        case KeeperDecision():
            return {"session_id": d["session_id"], "shot_id": d["shot_id"], "capture_id": d["capture_id"],
                    "revoked_at": d["revoked_at"]}
        case VoiceTurn():
            return {"session_id": d["session_id"], "started_at": d["started_at"]}
    raise TypeError(type(obj))


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.RLock()
        self.migrate()

    # --- schema --------------------------------------------------------------------------
    def schema_version(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> int:
        with self._lock:
            current = self.schema_version()
            for version, sql in enumerate(MIGRATIONS[current:], start=current + 1):
                self._conn.execute("BEGIN")
                try:
                    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                        self._conn.execute(stmt)
                    self._conn.execute(f"PRAGMA user_version={version}")
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise
            return self.schema_version()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- generic record access -----------------------------------------------------------
    def put(self, obj: T) -> T:
        table = _TABLES[type(obj)]
        cols = {"id": obj.id, **_columns(obj), "data": obj.model_dump_json()}  # type: ignore[attr-defined]
        names = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k}=excluded.{k}" for k in cols if k != "id")
        with self._lock:
            self._conn.execute(
                f"INSERT INTO {table} ({names}) VALUES ({marks}) ON CONFLICT(id) DO UPDATE SET {updates}",
                list(cols.values()),
            )
        return obj

    def get(self, cls: type[T], id_: str) -> T | None:
        with self._lock:
            row = self._conn.execute(f"SELECT data FROM {_TABLES[cls]} WHERE id=?", (id_,)).fetchone()
        return cls.model_validate_json(row["data"]) if row else None

    def query(self, cls: type[T], where: str = "1=1", params: tuple = (), order: str = "rowid") -> list[T]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT data FROM {_TABLES[cls]} WHERE {where} ORDER BY {order}", params
            ).fetchall()
        return [cls.model_validate_json(r["data"]) for r in rows]

    def update(self, cls: type[T], id_: str, fn: Callable[[T], T | None]) -> T | None:
        """Read-modify-write under the lock."""
        with self._lock:
            obj = self.get(cls, id_)
            if obj is None:
                return None
            new = fn(obj) or obj
            if hasattr(new, "updated_at"):
                new.updated_at = utcnow()  # type: ignore[attr-defined]
            return self.put(new)

    # --- typed helpers -------------------------------------------------------------------
    def list_sessions(self) -> list[Session]:
        return self.query(Session, order="created_at DESC")

    def shots(self, session_id: str) -> list[ShotRequirement]:
        return self.query(ShotRequirement, "session_id=?", (session_id,), "ordinal, rowid")

    def setup_revisions(self, session_id: str) -> list[SetupRevision]:
        return self.query(SetupRevision, "session_id=?", (session_id,), "revision")

    def captures(self, session_id: str, shot_id: str | None = None) -> list[Capture]:
        if shot_id:
            return self.query(Capture, "session_id=? AND shot_id=?", (session_id, shot_id), "seq")
        return self.query(Capture, "session_id=?", (session_id,), "seq")

    def next_capture_seq(self, session_id: str) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM captures WHERE session_id=?",
                                     (session_id,)).fetchone()
        return int(row[0])

    def insert_capture(self, cap: Capture) -> Capture:
        with self._lock:
            cap.seq = self.next_capture_seq(cap.session_id)
            return self.put(cap)

    def assessments_for(self, capture_id: str) -> list[Assessment]:
        return self.query(Assessment, "capture_id=?", (capture_id,), "created_at")

    def assessments(self, session_id: str) -> list[Assessment]:
        return self.query(Assessment, "session_id=?", (session_id,), "created_at")

    def latest_completed_assessment(self, capture_id: str) -> Assessment | None:
        items = self.query(Assessment, "capture_id=? AND status='completed'", (capture_id,), "created_at DESC")
        return items[0] if items else None

    def experiments(self, session_id: str) -> list[Experiment]:
        return self.query(Experiment, "session_id=?", (session_id,), "rowid")

    def open_experiment_for_baseline(self, baseline_capture_id: str) -> Experiment | None:
        items = self.query(Experiment, "baseline_capture_id=? AND follow_up_capture_id IS NULL",
                           (baseline_capture_id,), "rowid DESC")
        return items[0] if items else None

    def active_keepers(self, session_id: str) -> list[KeeperDecision]:
        return self.query(KeeperDecision, "session_id=? AND revoked_at IS NULL", (session_id,), "rowid")

    def active_keeper(self, shot_id: str) -> KeeperDecision | None:
        items = self.query(KeeperDecision, "shot_id=? AND revoked_at IS NULL", (shot_id,), "rowid DESC")
        return items[0] if items else None

    def voice_turns(self, session_id: str) -> list[VoiceTurn]:
        return self.query(VoiceTurn, "session_id=?", (session_id,), "started_at")

    # --- source files (ingestion ledger) -------------------------------------------------
    # One row per source path. ``status``: discovered | stabilizing | ingested | duplicate | pending_retry |
    # ignored | failed. ``snapshot`` holds the shot/setup attribution captured at first detection so an
    # interrupted ingest resumes with the original context after restart.
    def source_file(self, session_id: str, path: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM source_files WHERE session_id=? AND source_path=?",
                                     (session_id, path)).fetchone()
        return self._source_row(row)

    @staticmethod
    def _source_row(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        d["snapshot"] = json.loads(d["snapshot"]) if d["snapshot"] else None
        return d

    def source_by_hash(self, session_id: str, sha256: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM source_files WHERE session_id=? AND sha256=? AND status='ingested' LIMIT 1",
                (session_id, sha256),
            ).fetchone()
        return self._source_row(row)

    def record_source(self, session_id: str, path: str, *, size: int, mtime_ns: int, kind: str, status: str,
                      sha256: str | None = None, capture_id: str | None = None, snapshot: dict | None = None,
                      note: str | None = None) -> None:
        now = utcnow()
        with self._lock:
            self._conn.execute(
                """INSERT INTO source_files (session_id, source_path, size, mtime_ns, sha256, kind, capture_id,
                   status, first_seen_at, updated_at, snapshot, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(session_id, source_path) DO UPDATE SET size=excluded.size,
                   mtime_ns=excluded.mtime_ns, sha256=excluded.sha256, kind=excluded.kind,
                   capture_id=excluded.capture_id, status=excluded.status, updated_at=excluded.updated_at,
                   snapshot=COALESCE(excluded.snapshot, snapshot), note=excluded.note""",
                (session_id, path, size, mtime_ns, sha256, kind, capture_id, status, now, now,
                 json.dumps(snapshot) if snapshot else None, note),
            )

    def source_files(self, session_id: str, status: str | None = None) -> list[dict]:
        with self._lock:
            if status:
                rows = self._conn.execute("SELECT * FROM source_files WHERE session_id=? AND status=? ORDER BY id",
                                          (session_id, status)).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM source_files WHERE session_id=? ORDER BY id",
                                          (session_id,)).fetchall()
        return [self._source_row(r) for r in rows]  # type: ignore[misc]

    # --- timing --------------------------------------------------------------------------
    def add_timing(self, stage: str, wall: str, mono_ns: int, boot_id: str, *, session_id: str | None = None,
                   capture_id: str | None = None, assessment_id: str | None = None,
                   voice_turn_id: str | None = None, extra: dict | None = None) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO timing_marks (session_id, capture_id, assessment_id, voice_turn_id, stage, wall,
                   mono_ns, boot_id, extra) VALUES (?,?,?,?,?,?,?,?,?)""",
                (session_id, capture_id, assessment_id, voice_turn_id, stage, wall, mono_ns, boot_id,
                 json.dumps(extra) if extra else None),
            )

    def timing_marks(self, session_id: str | None = None) -> list[dict]:
        with self._lock:
            if session_id:
                rows = self._conn.execute("SELECT * FROM timing_marks WHERE session_id=? ORDER BY id",
                                          (session_id,)).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM timing_marks ORDER BY id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["extra"] = json.loads(d["extra"]) if d["extra"] else None
            out.append(d)
        return out


class AsyncStore:
    """Awaitable facade: ``await astore.get(Capture, id)`` runs ``Store.get`` on the DB thread."""

    def __init__(self, store: Store):
        self.sync = store
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db")

    def __getattr__(self, name: str) -> Callable[..., Any]:
        fn = getattr(self.sync, name)
        if not callable(fn):
            return fn

        async def call(*args: Any, **kwargs: Any) -> Any:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, lambda: fn(*args, **kwargs))

        return call

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)
        self.sync.close()
