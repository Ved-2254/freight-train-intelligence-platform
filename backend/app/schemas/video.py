from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class VideoLinks(BaseModel):
    self: str
    create_job: str = Field(description="POST here with {'video_id': ...} to start processing")


class VideoResponse(BaseModel):
    video_id: str
    original_filename: str = Field(description="Client-supplied name, kept as metadata only")
    size_bytes: int
    content_type: str | None
    status: Literal["ready", "deleted"]
    duration_seconds: float | None
    fps: float | None
    width: int | None
    height: int | None
    frame_count: int | None
    codec: str | None
    uploaded_at: datetime
    links: VideoLinks
