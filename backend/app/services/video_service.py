"""Video upload: stream to disk, enforce limits, validate with the pipeline's own decoder."""

from __future__ import annotations

import logging
import mimetypes
import re
import unicodedata
from pathlib import PurePath
from typing import BinaryIO

from app.api.errors import ApiError
from app.core.exceptions import VideoInputError
from app.core.ids import new_video_id, utc_now
from app.core.settings import ServiceSettings
from app.pipeline.video_reader import inspect_video
from app.repositories.video_repository import VideoRecord, VideoRepository
from app.storage.file_storage import LocalFileStorage, UploadTooLarge

log = logging.getLogger("wagon.api.videos")

_CONTENT_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo", ".mkv": "video/x-matroska"}


def sanitize_filename(name: str | None) -> str:
    """Display-only copy of the client filename: no directories, control chars or excess length."""
    if not name:
        return "upload"
    base = PurePath(name.replace("\\", "/")).name
    base = unicodedata.normalize("NFC", base)
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return base[:255] or "upload"


class VideoService:
    def __init__(self, settings: ServiceSettings, repo: VideoRepository, storage: LocalFileStorage):
        self.settings = settings
        self.repo = repo
        self.storage = storage

    def check_free_space(self, needed: int = 0) -> None:
        if self.storage.free_bytes() < self.settings.min_free_disk_bytes + needed:
            raise ApiError("INSUFFICIENT_STORAGE", "Not enough free disk space on the server to accept this request")

    def upload(self, stream: BinaryIO, filename: str | None, declared_type: str | None, content_length: int | None) -> VideoRecord:
        original = sanitize_filename(filename)
        ext = PurePath(original).suffix.lower()
        allowed = self.settings.extension_list
        if ext not in allowed:
            raise ApiError(
                "UNSUPPORTED_FILE_TYPE",
                f"Unsupported file type '{ext or '(none)'}'. Supported: {', '.join(allowed)}",
                {"supported_extensions": allowed},
            )
        if content_length is not None and content_length > self.settings.max_upload_bytes:
            raise self._too_large()
        self.check_free_space(content_length or 0)

        tmp = self.storage.new_temporary_path(ext)
        try:
            size = self.storage.write_stream(stream, tmp, self.settings.max_upload_bytes)
        except UploadTooLarge:
            raise self._too_large() from None
        except OSError as exc:
            log.exception("Failed to store upload")
            if getattr(exc, "errno", None) == 28:  # ENOSPC
                raise ApiError("INSUFFICIENT_STORAGE", "The server ran out of disk space while storing the upload") from None
            raise
        try:
            if size == 0:
                raise ApiError("EMPTY_UPLOAD", "The uploaded file is empty")
            try:
                meta = inspect_video(tmp)
            except VideoInputError as exc:
                log.info("Rejected upload %r: %s", original, exc)
                raise ApiError(
                    "UNSUPPORTED_VIDEO", "The file could not be decoded as a video (corrupt or unsupported codec)"
                ) from None
            video_id = new_video_id()
            key = self.storage.upload_key(video_id, ext)
            self.storage.move_into(tmp, key)
        finally:
            tmp.unlink(missing_ok=True)

        record = VideoRecord(
            video_id=video_id,
            original_filename=original,
            storage_key=key,
            extension=ext,
            content_type=_CONTENT_TYPES.get(ext) or mimetypes.guess_type(original)[0] or declared_type,
            size_bytes=size,
            status="ready",
            duration_seconds=meta.duration_seconds,
            fps=meta.fps,
            width=meta.width,
            height=meta.height,
            frame_count=meta.frame_count,
            codec=meta.codec,
            uploaded_at=utc_now(),
            deleted_at=None,
        )
        try:
            self.repo.create(record)
        except Exception:
            self.storage.delete(key)
            raise
        log.info("Stored video %s (%s, %d bytes)", video_id, original, size)
        return record

    def get(self, video_id: str) -> VideoRecord:
        rec = self.repo.get(video_id)
        if rec is None:
            raise ApiError("VIDEO_NOT_FOUND", f"Video '{video_id}' does not exist")
        return rec

    def delete(self, video_id: str) -> VideoRecord:
        rec = self.get(video_id)
        if rec.status == "deleted":
            return rec
        deleted, active = self.repo.mark_deleted_if_unused(video_id)
        if not deleted and active:
            raise ApiError(
                "VIDEO_IN_USE", "The video is used by a queued or running job; cancel or wait for it first",
                {"active_jobs": active},
            )
        self.storage.delete(rec.storage_key)
        return self.get(video_id)

    def _too_large(self) -> ApiError:
        limit = self.settings.max_upload_bytes
        return ApiError(
            "UPLOAD_TOO_LARGE", f"The upload exceeds the maximum size of {limit} bytes", {"max_upload_bytes": limit}
        )
