from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class JobOptions(BaseModel):
    """Optional, validated processing parameters. Anything not listed is rejected (422).

    Omitted options use the pipeline defaults from backend/configs/default.yaml. The model
    and all filesystem paths are fixed server-side and cannot be chosen by clients.
    """

    model_config = ConfigDict(extra="forbid")

    target_fps: float | None = Field(None, ge=1, le=60, description="Analysis sampling rate (never upsamples)")
    confidence_threshold: float | None = Field(None, ge=0.05, le=0.95, description="Detector confidence threshold")
    counting_mode: Literal["registry", "line"] | None = Field(None, description="Wagon counting strategy")
    line_position: float | None = Field(None, ge=0.05, le=0.95, description="Reference line, fraction of the frame")
    travel_axis: Literal["auto", "x", "y"] | None = None
    write_video: bool | None = Field(None, description="Render the annotated video (default true)")

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_id: str = Field(pattern=r"^vid_[0-9a-f]{32}$")
    options: JobOptions = Field(default_factory=JobOptions)


class JobError(BaseModel):
    code: str
    message: str


class ExportLinks(BaseModel):
    json_: str = Field(alias="json")
    csv: str
    tracks_csv: str

    model_config = ConfigDict(populate_by_name=True)


class JobLinks(BaseModel):
    self: str
    video_source: str
    cancel: str
    results: str | None = None
    annotated_video: str | None = None
    exports: ExportLinks | None = None


class JobResultSummary(BaseModel):
    total_wagons: int = Field(description="Counted wagons excluding the classes in excluded_classes (e.g. Locomotive)")
    total_rolling_stock: int = Field(description="All counted records, including excluded classes")
    excluded_classes: list[str]
    type_counts: dict[str, int]
    not_counted: int
    sequence_completeness: str | None
    uncertain_sequence_items: int | None
    warnings: int
    annotated_video_codec: str | None
    browser_playable_video: bool | None


class JobResponse(BaseModel):
    job_id: str
    video_id: str
    video_filename: str | None = Field(None, description="Original name of the uploaded video (metadata only)")
    status: JobStatus
    stage: str | None = Field(description="Current pipeline stage, e.g. detecting_and_tracking")
    progress_percent: float | None = Field(
        description="0-100 from real pipeline milestones/frames; null when it cannot be computed"
    )
    message: str | None
    cancel_requested: bool
    attempts: int = Field(description="Processing attempts (an interrupted job is re-queued once)")
    options: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime
    error: JobError | None
    result_summary: JobResultSummary | None
    links: JobLinks


class JobCreatedResponse(BaseModel):
    job_id: str
    video_id: str
    status: JobStatus
    created_at: datetime
    status_url: str
    poll_interval_seconds: float = Field(description="Suggested polling interval for GET status_url")


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int


class CancelResponse(BaseModel):
    job_id: str
    status: JobStatus
    cancel_requested: bool
    message: str
