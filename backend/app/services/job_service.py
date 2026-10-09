"""Job creation, lookup, listing, cancellation and response building."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.api.errors import ApiError
from app.core.ids import new_job_id
from app.repositories.job_repository import (
    DuplicateActiveJob,
    IdempotencyConflict,
    InvalidTransition,
    JobRecord,
    JobRepository,
    VideoNotAvailable,
)
from app.repositories.video_repository import VideoRepository
from app.schemas.job import (
    CancelResponse,
    ExportLinks,
    JobError,
    JobLinks,
    JobOptions,
    JobResponse,
    JobResultSummary,
)
from app.services.links import LinkBuilder
from app.services.video_service import VideoService


def options_hash(options: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(options, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class JobService:
    def __init__(self, jobs: JobRepository, videos: VideoRepository, video_service: VideoService, links: LinkBuilder):
        self.jobs = jobs
        self.videos = videos
        self.video_service = video_service
        self.links = links

    def create(self, video_id: str, options: JobOptions, idempotency_key: str | None) -> tuple[JobRecord, bool]:
        video = self.videos.get(video_id)
        if video is None:
            raise ApiError("VIDEO_NOT_FOUND", f"Video '{video_id}' does not exist")
        if video.status != "ready":
            raise ApiError("VIDEO_NOT_AVAILABLE", f"Video '{video_id}' has been deleted")
        self.video_service.check_free_space()
        opts = options.as_dict()
        try:
            return self.jobs.create(new_job_id(), video_id, opts, options_hash(opts), idempotency_key)
        except VideoNotAvailable:
            raise ApiError("VIDEO_NOT_AVAILABLE", f"Video '{video_id}' is not available") from None
        except DuplicateActiveJob as exc:
            raise ApiError(
                "JOB_ALREADY_ACTIVE",
                "An identical job for this video is already queued or running",
                {"job_id": exc.job_id, "status_url": self.links.job(exc.job_id)},
            ) from None
        except IdempotencyConflict as exc:
            raise ApiError(
                "IDEMPOTENCY_KEY_REUSED",
                "This Idempotency-Key was already used for a different request",
                {"job_id": exc.job_id},
            ) from None

    def get(self, job_id: str) -> JobRecord:
        job = self.jobs.get(job_id)
        if job is None:
            raise ApiError("JOB_NOT_FOUND", f"Job '{job_id}' does not exist")
        return job

    def cancel(self, job_id: str) -> CancelResponse:
        self.get(job_id)
        try:
            status = self.jobs.request_cancel(job_id)
        except KeyError:
            raise ApiError("JOB_NOT_FOUND", f"Job '{job_id}' does not exist") from None
        except InvalidTransition as exc:
            raise ApiError(
                "JOB_NOT_CANCELLABLE", f"Job is already {exc.status} and cannot be cancelled", {"status": exc.status}
            ) from None
        if status == "cancelled":
            msg = "Job cancelled before processing started"
        else:
            msg = "Cancellation requested; processing stops at the next frame check (usually within a second)"
        return CancelResponse(job_id=job_id, status=status, cancel_requested=True, message=msg)

    # ----------------------------------------------------------------- views
    def to_response(self, job: JobRecord) -> JobResponse:
        completed = job.status == "completed"
        summary = job.summary
        links = JobLinks(
            self=self.links.job(job.job_id),
            video_source=self.links.video(job.video_id),
            cancel=self.links.cancel(job.job_id),
        )
        if completed:
            links.results = self.links.results(job.job_id)
            if job.options.get("write_video", True):
                links.annotated_video = self.links.annotated_video(job.job_id)
            links.exports = ExportLinks(
                json=self.links.export(job.job_id, "json"),
                csv=self.links.export(job.job_id, "csv"),
                tracks_csv=self.links.export(job.job_id, "tracks_csv"),
            )
        error = None
        if job.status in ("failed", "cancelled") and job.error_code:
            error = JobError(code=job.error_code, message=job.error_message or "")
        video = self.videos.get(job.video_id)
        return JobResponse(
            job_id=job.job_id,
            video_id=job.video_id,
            video_filename=video.original_filename if video else None,
            status=job.status,
            stage=job.stage,
            progress_percent=None if job.progress_percent is None else round(job.progress_percent, 1),
            message=job.message,
            cancel_requested=bool(job.cancel_requested),
            attempts=job.attempts,
            options=job.options,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            updated_at=job.updated_at,
            error=error,
            result_summary=JobResultSummary(**summary) if completed and summary else None,
            links=links,
        )
