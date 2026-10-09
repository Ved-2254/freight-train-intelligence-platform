"""SQLite connection management and schema.

Single-machine design: one SQLite file in WAL mode shared by the API process and worker
process(es). Every operation opens a short-lived connection, so it is safe across threads and
processes. Write transactions that must be atomic (job claim, state transitions) use
`BEGIN IMMEDIATE`. Moving to PostgreSQL means re-implementing the repository classes, not the
routes or services.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS videos (
    video_id          TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    storage_key       TEXT NOT NULL UNIQUE,
    extension         TEXT NOT NULL,
    content_type      TEXT,
    size_bytes        INTEGER NOT NULL CHECK (size_bytes >= 0),
    status            TEXT NOT NULL CHECK (status IN ('ready', 'deleted')),
    duration_seconds  REAL,
    fps               REAL,
    width             INTEGER,
    height            INTEGER,
    frame_count       INTEGER,
    codec             TEXT,
    uploaded_at       TEXT NOT NULL,
    deleted_at        TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id               TEXT PRIMARY KEY,
    video_id             TEXT NOT NULL REFERENCES videos (video_id),
    status               TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    stage                TEXT,
    progress_percent     REAL CHECK (progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)),
    message              TEXT,
    options_json         TEXT NOT NULL,
    options_hash         TEXT NOT NULL,
    idempotency_key      TEXT UNIQUE,
    cancel_requested     INTEGER NOT NULL DEFAULT 0,
    attempts             INTEGER NOT NULL DEFAULT 0,
    error_code           TEXT,
    error_message        TEXT,
    internal_error       TEXT,
    config_snapshot_json TEXT,
    model_json           TEXT,
    summary_json         TEXT,
    worker_id            TEXT,
    created_at           TEXT NOT NULL,
    started_at           TEXT,
    finished_at          TEXT,
    heartbeat_at         TEXT,
    updated_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_jobs_status_created ON jobs (status, created_at);
CREATE INDEX IF NOT EXISTS ix_jobs_video ON jobs (video_id);
CREATE INDEX IF NOT EXISTS ix_jobs_created ON jobs (created_at);
-- At most one active (queued/running) job per video + identical options: duplicate guard.
CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_active
    ON jobs (video_id, options_hash) WHERE status IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS artifacts (
    job_id      TEXT NOT NULL REFERENCES jobs (job_id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL CHECK (size_bytes >= 0),
    media_type  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (job_id, kind)
);

CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id      TEXT PRIMARY KEY,
    hostname       TEXT,
    pid            INTEGER,
    started_at     TEXT NOT NULL,
    last_seen      TEXT NOT NULL,
    current_job_id TEXT
);
"""


class Database:
    def __init__(self, path: Path, timeout: float = 30.0):
        self.path = Path(path)
        self.timeout = timeout

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)  # autocommit
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = %d" % int(self.timeout * 1000))
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Autocommit connection for single statements / reads."""
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """Explicit transaction; IMMEDIATE takes the write lock up front (no upgrade deadlocks)."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create the database file and schema if missing (idempotent)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA)
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {row['version']} is newer than this code ({SCHEMA_VERSION})"
                )

    def ping(self) -> None:
        with self.connect() as conn:
            conn.execute("SELECT 1").fetchone()
