"""Persistence for uploaded videos."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.core.ids import utc_now
from app.repositories.database import Database


@dataclass(frozen=True)
class VideoRecord:
    video_id: str
    original_filename: str
    storage_key: str
    extension: str
    content_type: str | None
    size_bytes: int
    status: str
    duration_seconds: float | None
    fps: float | None
    width: int | None
    height: int | None
    frame_count: int | None
    codec: str | None
    uploaded_at: str
    deleted_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "VideoRecord":
        return cls(**{k: row[k] for k in row.keys()})


class VideoRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, record: VideoRecord) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO videos (video_id, original_filename, storage_key, extension, content_type,
                       size_bytes, status, duration_seconds, fps, width, height, frame_count, codec,
                       uploaded_at, deleted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.video_id, record.original_filename, record.storage_key, record.extension,
                 record.content_type, record.size_bytes, record.status, record.duration_seconds, record.fps,
                 record.width, record.height, record.frame_count, record.codec, record.uploaded_at,
                 record.deleted_at),
            )

    def get(self, video_id: str) -> VideoRecord | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()
        return VideoRecord.from_row(row) if row else None

    def mark_deleted_if_unused(self, video_id: str) -> tuple[bool, int]:
        """Atomically mark a ready video deleted unless active jobs use it.

        Returns (deleted, active_job_count).
        """
        with self.db.transaction() as conn:
            active = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE video_id = ? AND status IN ('queued', 'running')", (video_id,)
            ).fetchone()[0]
            if active:
                return False, active
            cur = conn.execute(
                "UPDATE videos SET status = 'deleted', deleted_at = ? WHERE video_id = ? AND status = 'ready'",
                (utc_now(), video_id),
            )
            return cur.rowcount == 1, 0
