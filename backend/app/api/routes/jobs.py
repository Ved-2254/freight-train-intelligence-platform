from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import FileResponse

from app.api.dependencies import Container, get_container, valid_job_id
from app.api.errors import ApiError
from app.core.ids import to_utc_string
from app.repositories.job_repository import JobRecord
from app.schemas.common import error_responses
from app.schemas.job import (
    CancelResponse,
    JobCreatedResponse,
    JobCreateRequest,
    JobListResponse,
    JobResponse,
    JobResultSummary,
    JobStatus,
)
from app.schemas.result import JobResultsResponse
from app.services.result_service import EXPORT_FORMATS, load_json

router = APIRouter(prefix="/jobs", tags=["jobs"])

POLL_INTERVAL_SECONDS = 2.0


@router.post(
    "",
    status_code=202,
    response_model=JobCreatedResponse,
    summary="Start processing an uploaded video (asynchronous)",
    description=(
        "Creates a queued job and returns immediately with 202. Poll `status_url` until `status` is "
        "`completed`, `failed` or `cancelled`. Send an `Idempotency-Key` header to make client retries "
        "safe: repeating the same request with the same key returns the original job. An identical "
        "job (same video and options) that is still queued/running is rejected with 409 JOB_ALREADY_ACTIVE."
    ),
    responses=error_responses(404, 409, 422, 507),
)
def create_job(
    body: JobCreateRequest,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=200),
    c: Container = Depends(get_container),
) -> JobCreatedResponse:
    job, created = c.job_service.create(body.video_id, body.options, idempotency_key)
    status_url = c.links.job(job.job_id)
    response.headers["Location"] = status_url
    if not created:
        response.headers["Idempotent-Replayed"] = "true"
    return JobCreatedResponse(
        job_id=job.job_id, video_id=job.video_id, status=job.status, created_at=job.created_at,
        status_url=status_url, poll_interval_seconds=POLL_INTERVAL_SECONDS,
    )


@router.get("", response_model=JobListResponse, summary="List jobs, newest first")
def list_jobs(
    status: JobStatus | None = Query(None),
    video_id: str | None = Query(None, pattern=r"^vid_[0-9a-f]{32}$"),
    created_after: datetime | None = Query(None, description="ISO-8601; naive values are treated as UTC"),
    created_before: datetime | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    c: Container = Depends(get_container),
) -> JobListResponse:
    items, total = c.jobs.list(
        status=status,
        video_id=video_id,
        created_after=to_utc_string(created_after) if created_after else None,
        created_before=to_utc_string(created_before) if created_before else None,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(items=[c.job_service.to_response(j) for j in items], total=total, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobResponse, summary="Job status and progress",
            responses=error_responses(404))
def get_job(job_id: str, c: Container = Depends(get_container)) -> JobResponse:
    return c.job_service.to_response(c.job_service.get(valid_job_id(job_id)))


@router.post(
    "/{job_id}/cancel",
    response_model=CancelResponse,
    summary="Cancel a job",
    description=(
        "A queued job is cancelled immediately. A running job is cancelled cooperatively: the pipeline "
        "checks the request between frames and stops (normally within about a second); poll the job "
        "until its status is `cancelled`. Finished jobs return 409 JOB_NOT_CANCELLABLE."
    ),
    responses=error_responses(404, 409),
)
def cancel_job(job_id: str, c: Container = Depends(get_container)) -> CancelResponse:
    return c.job_service.cancel(valid_job_id(job_id))


def _completed_job(job_id: str, c: Container) -> JobRecord:
    job = c.job_service.get(valid_job_id(job_id))
    if job.status == "completed":
        return job
    if job.status == "failed":
        raise ApiError("JOB_FAILED", "The job failed; no results are available",
                       {"error_code": job.error_code, "error_message": job.error_message})
    if job.status == "cancelled":
        raise ApiError("JOB_CANCELLED", "The job was cancelled; no results are available")
    raise ApiError("JOB_NOT_COMPLETED", "The job has not finished yet",
                   {"status": job.status, "progress_percent": job.progress_percent, "status_url": c.links.job(job_id)})


def _artifact_file(c: Container, job_id: str, kind: str):
    art = c.artifacts.get(job_id, kind)
    if art is None:
        raise ApiError("ARTIFACT_NOT_AVAILABLE", f"This job has no '{kind}' output")
    path = c.storage.resolve(art.storage_key)
    if not path.is_file():
        raise ApiError("ARTIFACT_NOT_AVAILABLE", f"The '{kind}' output is missing on the server")
    return art, path


@router.get(
    "/{job_id}/results",
    response_model=JobResultsResponse,
    summary="Structured results of a completed job",
    description="Wraps the pipeline's result.json (schema_version 1.0; see documentation/output_schema.md). "
    "Returns 409 while the job is queued/running, or if it failed or was cancelled.",
    responses=error_responses(404, 409),
)
def get_results(job_id: str, c: Container = Depends(get_container)) -> JobResultsResponse:
    job = _completed_job(job_id, c)
    _, path = _artifact_file(c, job.job_id, "result_public_json")
    view = c.job_service.to_response(job)
    return JobResultsResponse(
        job_id=job.job_id,
        video_id=job.video_id,
        status=job.status,
        summary=JobResultSummary(**job.summary) if job.summary else view.result_summary,
        result=load_json(path),
        links=view.links,
    )


@router.get(
    "/{job_id}/video",
    summary="Annotated output video (supports HTTP Range for seeking)",
    response_class=FileResponse,
    responses={200: {"content": {"video/mp4": {}}}, **error_responses(404, 409)},
)
def get_annotated_video(
    job_id: str,
    download: bool = Query(False, description="true = Content-Disposition: attachment"),
    c: Container = Depends(get_container),
) -> FileResponse:
    job = _completed_job(job_id, c)
    art, path = _artifact_file(c, job.job_id, "annotated_video")
    return FileResponse(
        path,
        media_type=art.media_type,
        filename=f"{job.job_id}_annotated.mp4",
        content_disposition_type="attachment" if download else "inline",
    )


@router.get(
    "/{job_id}/exports/{fmt}",
    summary="Download results as JSON or CSV",
    description="`json`: client-safe result.json; `csv`: wagon sequence table (wagons.csv); "
    "`tracks_csv`: per-frame observations (tracks.csv).",
    response_class=FileResponse,
    responses={200: {"content": {"application/json": {}, "text/csv": {}}}, **error_responses(404, 409, 422)},
)
def export(job_id: str, fmt: Literal["json", "csv", "tracks_csv"], c: Container = Depends(get_container)) -> FileResponse:
    job = _completed_job(job_id, c)
    kind, suffix = EXPORT_FORMATS[fmt]
    art, path = _artifact_file(c, job.job_id, kind)
    media = art.media_type + ("; charset=utf-8" if art.media_type.startswith("text/") else "")
    return FileResponse(path, media_type=media, filename=f"{job.job_id}_{suffix}")
