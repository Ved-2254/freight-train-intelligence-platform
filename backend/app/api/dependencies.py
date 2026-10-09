"""Service container stored on `app.state` and FastAPI dependency accessors."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.api.errors import ApiError
from app.core.ids import JOB_ID_RE, VIDEO_ID_RE
from app.core.settings import ServiceSettings
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.database import Database
from app.repositories.job_repository import JobRepository, WorkerRepository
from app.repositories.video_repository import VideoRepository
from app.services.job_service import JobService
from app.services.links import LinkBuilder
from app.services.video_service import VideoService
from app.storage.file_storage import LocalFileStorage


@dataclass
class Container:
    settings: ServiceSettings
    db: Database
    storage: LocalFileStorage
    videos: VideoRepository
    jobs: JobRepository
    artifacts: ArtifactRepository
    workers: WorkerRepository
    links: LinkBuilder
    video_service: VideoService
    job_service: JobService


def build_container(settings: ServiceSettings) -> Container:
    db = Database(settings.db_path)
    storage = LocalFileStorage(settings.storage_root)
    videos = VideoRepository(db)
    jobs = JobRepository(db)
    links = LinkBuilder(settings.public_base_url)
    video_service = VideoService(settings, videos, storage)
    return Container(
        settings=settings, db=db, storage=storage, videos=videos, jobs=jobs,
        artifacts=ArtifactRepository(db), workers=WorkerRepository(db), links=links,
        video_service=video_service, job_service=JobService(jobs, videos, video_service, links),
    )


def get_container(request: Request) -> Container:
    return request.app.state.container


def valid_job_id(job_id: str) -> str:
    if not JOB_ID_RE.match(job_id):
        raise ApiError("JOB_NOT_FOUND", f"Job '{job_id[:80]}' does not exist")
    return job_id


def valid_video_id(video_id: str) -> str:
    if not VIDEO_ID_RE.match(video_id):
        raise ApiError("VIDEO_NOT_FOUND", f"Video '{video_id[:80]}' does not exist")
    return video_id
