from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.api.dependencies import Container, get_container, valid_video_id
from app.repositories.video_repository import VideoRecord
from app.schemas.common import error_responses
from app.schemas.video import VideoLinks, VideoResponse

router = APIRouter(prefix="/videos", tags=["videos"])


def to_video_response(rec: VideoRecord, c: Container) -> VideoResponse:
    return VideoResponse(
        video_id=rec.video_id,
        original_filename=rec.original_filename,
        size_bytes=rec.size_bytes,
        content_type=rec.content_type,
        status=rec.status,
        duration_seconds=rec.duration_seconds,
        fps=rec.fps,
        width=rec.width,
        height=rec.height,
        frame_count=rec.frame_count,
        codec=rec.codec,
        uploaded_at=rec.uploaded_at,
        links=VideoLinks(self=c.links.video(rec.video_id), create_job=c.links.jobs()),
    )


@router.post(
    "",
    status_code=201,
    response_model=VideoResponse,
    summary="Upload a freight-train video (multipart/form-data, field `file`)",
    description=(
        "Accepts .mp4, .mov, .avi, .mkv (configurable) up to FTIP_MAX_UPLOAD_BYTES (default 2 GiB). "
        "The file is streamed to disk, then validated by decoding it with the pipeline's video reader. "
        "The original filename is stored as metadata only; the server generates the stored name."
    ),
    responses=error_responses(400, 413, 415, 422, 507),
)
def upload_video(request: Request, file: UploadFile = File(...), c: Container = Depends(get_container)) -> VideoResponse:
    rec = c.video_service.upload(file.file, file.filename, file.content_type, content_length=None)
    return to_video_response(rec, c)


@router.get("/{video_id}", response_model=VideoResponse, summary="Get uploaded video metadata",
            responses=error_responses(404))
def get_video(video_id: str, c: Container = Depends(get_container)) -> VideoResponse:
    return to_video_response(c.video_service.get(valid_video_id(video_id)), c)


@router.delete(
    "/{video_id}",
    response_model=VideoResponse,
    summary="Delete an uploaded video file",
    description="Refused (409 VIDEO_IN_USE) while a queued or running job uses the video. "
    "Completed job results are kept. The metadata record remains with status `deleted`.",
    responses=error_responses(404, 409),
)
def delete_video(video_id: str, c: Container = Depends(get_container)) -> VideoResponse:
    return to_video_response(c.video_service.delete(valid_video_id(video_id)), c)
