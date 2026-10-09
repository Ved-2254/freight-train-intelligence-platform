"""Server-generated identifiers and UTC timestamps (stored as ISO-8601 strings ending in 'Z')."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

VIDEO_ID_RE = re.compile(r"^vid_[0-9a-f]{32}$")
JOB_ID_RE = re.compile(r"^job_[0-9a-f]{32}$")


def new_video_id() -> str:
    return f"vid_{uuid.uuid4().hex}"


def new_job_id() -> str:
    return f"job_{uuid.uuid4().hex}"


def utc_now() -> str:
    """Current UTC time, millisecond precision; lexicographic order == chronological order."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_utc_string(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
