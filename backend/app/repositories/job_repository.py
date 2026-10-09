"""Persistence and state transitions for processing jobs.

State machine (every transition is a conditional UPDATE, so concurrent writers cannot
overwrite a newer state):

    queued  --claim-->   running --complete--> completed
       |                    |----fail------> failed
       |                    |----cancel----> cancelled
       |                    '----stale + attempts < max --> queued (re-queued once by default)
       '----cancel--> cancelled
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.core.ids import utc_now
from app.repositories.artifact_repository import ArtifactRecord, ArtifactRepository
from app.repositories.database import Database

ACTIVE_STATUSES = ("queued", "running")
FINAL_STATUSES = ("completed", "failed", "cancelled")
ALL_STATUSES = ACTIVE_STATUSES + FINAL_STATUSES


class VideoNotAvailable(Exception):
    pass


class DuplicateActiveJob(Exception):
    def __init__(self, job_id: str):
        super().__init__(job_id)
        self.job_id = job_id


class IdempotencyConflict(Exception):
    """The idempotency key was already used for a different request."""

    def __init__(self, job_id: str):
        super().__init__(job_id)
        self.job_id = job_id


class InvalidTransition(Exception):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    video_id: str
    status: str
    stage: str | None
    progress_percent: float | None
    message: str | None
    options_json: str
    options_hash: str
    idempotency_key: str | None
    cancel_requested: int
    attempts: int
    error_code: str | None
    error_message: str | None
    internal_error: str | None
    config_snapshot_json: str | None
    model_json: str | None
    summary_json: str | None
    worker_id: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    heartbeat_at: str | None
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "JobRecord":
        return cls(**{k: row[k] for k in row.keys()})

    @property
    def options(self) -> dict[str, Any]:
        return json.loads(self.options_json)

    @property
    def summary(self) -> dict[str, Any] | None:
        return json.loads(self.summary_json) if self.summary_json else None


class JobRepository:
    def __init__(self, db: Database):
        self.db = db
        self.artifacts = ArtifactRepository(db)

    # ------------------------------------------------------------- create / read
    def create(
        self, job_id: str, video_id: str, options: dict[str, Any], options_hash: str, idempotency_key: str | None
    ) -> tuple[JobRecord, bool]:
        """Create a queued job. Returns (job, created). `created` is False when an identical
        request with the same idempotency key already exists (the existing job is returned)."""
        now = utc_now()
        with self.db.transaction() as conn:
            if idempotency_key:
                row = conn.execute("SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                if row is not None:
                    existing = JobRecord.from_row(row)
                    if existing.video_id == video_id and existing.options_hash == options_hash:
                        return existing, False
                    raise IdempotencyConflict(existing.job_id)
            video = conn.execute("SELECT status FROM videos WHERE video_id = ?", (video_id,)).fetchone()
            if video is None or video["status"] != "ready":
                raise VideoNotAvailable(video_id)
            active = conn.execute(
                "SELECT job_id FROM jobs WHERE video_id = ? AND options_hash = ? AND status IN ('queued', 'running')",
                (video_id, options_hash),
            ).fetchone()
            if active is not None:
                raise DuplicateActiveJob(active["job_id"])
            conn.execute(
                """INSERT INTO jobs (job_id, video_id, status, stage, progress_percent, message, options_json,
                       options_hash, idempotency_key, created_at, updated_at)
                   VALUES (?, ?, 'queued', 'queued', 0, 'Waiting for a worker', ?, ?, ?, ?, ?)""",
                (job_id, video_id, json.dumps(options, sort_keys=True), options_hash, idempotency_key, now, now),
            )
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return JobRecord.from_row(row), True

    def get(self, job_id: str) -> JobRecord | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return JobRecord.from_row(row) if row else None

    def list(
        self,
        status: str | None = None,
        video_id: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[JobRecord], int]:
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if video_id:
            where.append("video_id = ?")
            params.append(video_id)
        if created_after:
            where.append("created_at >= ?")
            params.append(created_after)
        if created_before:
            where.append("created_at < ?")
            params.append(created_before)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self.db.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM jobs {clause}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM jobs {clause} ORDER BY created_at DESC, job_id DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return [JobRecord.from_row(r) for r in rows], total

    def count_active_for_video(self, video_id: str) -> int:
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE video_id = ? AND status IN ('queued', 'running')", (video_id,)
            ).fetchone()[0]

    # --------------------------------------------------------------- worker side
    def claim_next(self, worker_id: str) -> JobRecord | None:
        """Atomically move the oldest queued job to running. Safe with several workers."""
        now = utc_now()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT job_id FROM jobs WHERE status = 'queued' ORDER BY created_at, job_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            cur = conn.execute(
                """UPDATE jobs SET status = 'running', stage = 'starting', progress_percent = 0,
                       message = 'Job started', attempts = attempts + 1, worker_id = ?, started_at = ?,
                       heartbeat_at = ?, updated_at = ?, error_code = NULL, error_message = NULL,
                       internal_error = NULL
                   WHERE job_id = ? AND status = 'queued'""",
                (worker_id, now, now, now, row["job_id"]),
            )
            if cur.rowcount != 1:
                return None
            claimed = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
        return JobRecord.from_row(claimed)

    def update_progress(self, job_id: str, stage: str, percent: float | None, message: str) -> bool:
        now = utc_now()
        with self.db.connect() as conn:
            cur = conn.execute(
                """UPDATE jobs SET stage = ?, progress_percent = COALESCE(?, progress_percent), message = ?,
                       heartbeat_at = ?, updated_at = ?
                   WHERE job_id = ? AND status = 'running'""",
                (stage, percent, message, now, now, job_id),
            )
        return cur.rowcount == 1

    def heartbeat(self, job_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE jobs SET heartbeat_at = ? WHERE job_id = ? AND status = 'running'", (utc_now(), job_id))

    def is_cancel_requested(self, job_id: str) -> bool:
        with self.db.connect() as conn:
            row = conn.execute("SELECT cancel_requested FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def complete(
        self,
        job_id: str,
        summary: dict[str, Any],
        config_snapshot: dict[str, Any],
        model: dict[str, Any],
        artifacts: list[ArtifactRecord],
    ) -> bool:
        now = utc_now()
        with self.db.transaction() as conn:
            cur = conn.execute(
                """UPDATE jobs SET status = 'completed', stage = 'completed', progress_percent = 100,
                       message = 'Processing complete', summary_json = ?, config_snapshot_json = ?,
                       model_json = ?, finished_at = ?, updated_at = ?
                   WHERE job_id = ? AND status = 'running'""",
                (json.dumps(summary), json.dumps(config_snapshot), json.dumps(model), now, now, job_id),
            )
            if cur.rowcount != 1:
                return False
            self.artifacts.replace_for_job(job_id, artifacts, conn)
        return True

    def fail(
        self,
        job_id: str,
        error_code: str,
        error_message: str,
        internal_error: str | None,
        artifacts: list[ArtifactRecord] | None = None,
    ) -> bool:
        now = utc_now()
        with self.db.transaction() as conn:
            cur = conn.execute(
                """UPDATE jobs SET status = 'failed', stage = 'failed', message = ?, error_code = ?,
                       error_message = ?, internal_error = ?, finished_at = ?, updated_at = ?
                   WHERE job_id = ? AND status = 'running'""",
                (error_message, error_code, error_message, internal_error, now, now, job_id),
            )
            if cur.rowcount != 1:
                return False
            if artifacts is not None:
                self.artifacts.replace_for_job(job_id, artifacts, conn)
        return True

    def mark_cancelled(self, job_id: str, message: str = "Cancelled on request") -> bool:
        now = utc_now()
        with self.db.connect() as conn:
            cur = conn.execute(
                """UPDATE jobs SET status = 'cancelled', stage = 'cancelled', message = ?, error_code = 'JOB_CANCELLED',
                       error_message = ?, finished_at = ?, updated_at = ?
                   WHERE job_id = ? AND status IN ('queued', 'running')""",
                (message, message, now, now, job_id),
            )
        return cur.rowcount == 1

    def request_cancel(self, job_id: str) -> str:
        """Cancel a queued job immediately or flag a running one. Returns the resulting status
        ('cancelled' or 'running'); raises InvalidTransition for finished jobs, KeyError if unknown."""
        now = utc_now()
        with self.db.transaction() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            status = row["status"]
            if status == "queued":
                conn.execute(
                    """UPDATE jobs SET status = 'cancelled', stage = 'cancelled', cancel_requested = 1,
                           message = 'Cancelled before processing started', error_code = 'JOB_CANCELLED',
                           error_message = 'Cancelled before processing started', finished_at = ?, updated_at = ?
                       WHERE job_id = ? AND status = 'queued'""",
                    (now, now, job_id),
                )
                return "cancelled"
            if status == "running":
                conn.execute(
                    "UPDATE jobs SET cancel_requested = 1, message = 'Cancellation requested', updated_at = ? "
                    "WHERE job_id = ? AND status = 'running'",
                    (now, job_id),
                )
                return "running"
            raise InvalidTransition(status)

    def recover_stale(
        self, stale_before: str, max_attempts: int, dead_worker_before: str | None = None
    ) -> list[tuple[str, str]]:
        """Handle running jobs whose heartbeat stopped (worker crashed or was killed).

        A job is abandoned when its own heartbeat is older than `stale_before`, or (faster) when
        the worker that claimed it has no liveness heartbeat newer than `dead_worker_before`.

        Jobs with attempts < max_attempts are re-queued; others fail with WORKER_INTERRUPTED; a
        stale job that had a cancel request is cancelled. Returns [(job_id, new_status)].
        """
        now = utc_now()
        out: list[tuple[str, str]] = []
        with self.db.transaction() as conn:
            dead_clause, params = "", [stale_before]
            if dead_worker_before is not None:
                dead_clause = (" OR worker_id IS NULL OR worker_id NOT IN "
                               "(SELECT worker_id FROM worker_heartbeats WHERE last_seen >= ?)")
                params.append(dead_worker_before)
            rows = conn.execute(
                "SELECT job_id, attempts, cancel_requested FROM jobs WHERE status = 'running' "
                f"AND (heartbeat_at IS NULL OR heartbeat_at < ?{dead_clause})",
                params,
            ).fetchall()
            for r in rows:
                if r["cancel_requested"]:
                    conn.execute(
                        """UPDATE jobs SET status = 'cancelled', stage = 'cancelled', error_code = 'JOB_CANCELLED',
                               error_message = 'Cancelled (worker stopped)', message = 'Cancelled (worker stopped)',
                               finished_at = ?, updated_at = ? WHERE job_id = ? AND status = 'running'""",
                        (now, now, r["job_id"]),
                    )
                    out.append((r["job_id"], "cancelled"))
                elif r["attempts"] < max_attempts:
                    conn.execute(
                        """UPDATE jobs SET status = 'queued', stage = 'queued', progress_percent = 0,
                               message = 'Re-queued after the worker was interrupted', worker_id = NULL,
                               heartbeat_at = NULL, updated_at = ? WHERE job_id = ? AND status = 'running'""",
                        (now, r["job_id"]),
                    )
                    out.append((r["job_id"], "queued"))
                else:
                    msg = "Processing was interrupted (worker stopped) and the retry limit was reached"
                    conn.execute(
                        """UPDATE jobs SET status = 'failed', stage = 'failed', error_code = 'WORKER_INTERRUPTED',
                               error_message = ?, message = ?, finished_at = ?, updated_at = ?
                           WHERE job_id = ? AND status = 'running'""",
                        (msg, msg, now, now, r["job_id"]),
                    )
                    out.append((r["job_id"], "failed"))
        return out


class WorkerRepository:
    """Worker liveness records (used by /ready and for diagnostics)."""

    def __init__(self, db: Database):
        self.db = db

    def beat(self, worker_id: str, hostname: str, pid: int, started_at: str, current_job_id: str | None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO worker_heartbeats (worker_id, hostname, pid, started_at, last_seen, current_job_id)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (worker_id) DO UPDATE SET last_seen = excluded.last_seen,
                       current_job_id = excluded.current_job_id""",
                (worker_id, hostname, pid, started_at, utc_now(), current_job_id),
            )

    def remove(self, worker_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM worker_heartbeats WHERE worker_id = ?", (worker_id,))

    def alive_since(self, since: str) -> list[sqlite3.Row]:
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT worker_id, current_job_id, last_seen FROM worker_heartbeats WHERE last_seen >= ?", (since,)
            ).fetchall()
