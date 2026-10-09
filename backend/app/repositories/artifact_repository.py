"""Persistence for job output artifacts (files live in storage; only metadata here)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.repositories.database import Database


@dataclass(frozen=True)
class ArtifactRecord:
    job_id: str
    kind: str
    storage_key: str
    size_bytes: int
    media_type: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ArtifactRecord":
        return cls(**{k: row[k] for k in row.keys()})


class ArtifactRepository:
    def __init__(self, db: Database):
        self.db = db

    def replace_for_job(self, job_id: str, artifacts: list[ArtifactRecord], conn: sqlite3.Connection | None = None) -> None:
        """Replace all artifact rows for a job (a re-queued attempt overwrites the previous one)."""
        def _write(c: sqlite3.Connection) -> None:
            c.execute("DELETE FROM artifacts WHERE job_id = ?", (job_id,))
            c.executemany(
                "INSERT INTO artifacts (job_id, kind, storage_key, size_bytes, media_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(a.job_id, a.kind, a.storage_key, a.size_bytes, a.media_type, a.created_at) for a in artifacts],
            )

        if conn is not None:
            _write(conn)
        else:
            with self.db.transaction() as c:
                _write(c)

    def list_for_job(self, job_id: str) -> list[ArtifactRecord]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM artifacts WHERE job_id = ? ORDER BY kind", (job_id,)).fetchall()
        return [ArtifactRecord.from_row(r) for r in rows]

    def get(self, job_id: str, kind: str) -> ArtifactRecord | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE job_id = ? AND kind = ?", (job_id, kind)).fetchone()
        return ArtifactRecord.from_row(row) if row else None
