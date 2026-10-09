"""Local filesystem storage behind a small interface.

Layout under the storage root (default backend/storage/):
    uploads/{video_id}{ext}          uploaded source videos
    jobs/{job_id}/outputs/           pipeline outputs for one job
    temporary/                       in-progress uploads (cleaned on startup when old)

Callers only ever pass *storage keys* (relative POSIX paths built from server-generated IDs).
`resolve()` rejects anything that would escape the storage root. Raw paths are never returned
to API clients.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import BinaryIO

CHUNK_SIZE = 1024 * 1024


class StorageError(Exception):
    pass


class UnsafeStorageKey(StorageError):
    pass


class UploadTooLarge(StorageError):
    pass


class LocalFileStorage:
    UPLOADS = "uploads"
    JOBS = "jobs"
    TEMPORARY = "temporary"

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    # ------------------------------------------------------------------ setup
    def initialize(self) -> None:
        for sub in (self.UPLOADS, self.JOBS, self.TEMPORARY):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------- keys
    @staticmethod
    def upload_key(video_id: str, extension: str) -> str:
        return f"uploads/{video_id}{extension}"

    @staticmethod
    def job_output_key(job_id: str) -> str:
        return f"jobs/{job_id}/outputs"

    def resolve(self, key: str) -> Path:
        """Absolute path for a storage key; raises UnsafeStorageKey on traversal attempts."""
        if not key or "\\" in key or "\x00" in key:
            raise UnsafeStorageKey("invalid storage key")
        raw_parts = key.split("/")
        if any(part in ("", ".", "..") for part in raw_parts):  # canonical keys only
            raise UnsafeStorageKey("invalid storage key")
        pure = PurePosixPath(key)
        if pure.is_absolute() or ":" in pure.parts[0]:
            raise UnsafeStorageKey("invalid storage key")
        path = (self.root / Path(*pure.parts)).resolve()
        if path != self.root and self.root not in path.parents:
            raise UnsafeStorageKey("storage key escapes the storage root")
        return path

    def key_for(self, path: Path) -> str:
        """Storage key for a path inside the root (used to register pipeline outputs)."""
        rel = Path(path).resolve().relative_to(self.root)
        return rel.as_posix()

    # ------------------------------------------------------------- operations
    def new_temporary_path(self, suffix: str = "") -> Path:
        return self.root / self.TEMPORARY / f"{uuid.uuid4().hex}{suffix}.part"

    def write_stream(self, source: BinaryIO, dest: Path, max_bytes: int) -> int:
        """Copy a stream to `dest` in chunks, enforcing `max_bytes`. Removes `dest` on failure."""
        written = 0
        try:
            with open(dest, "xb") as out:
                while chunk := source.read(CHUNK_SIZE):
                    written += len(chunk)
                    if written > max_bytes:
                        raise UploadTooLarge(f"upload exceeds {max_bytes} bytes")
                    out.write(chunk)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        return written

    def move_into(self, src: Path, key: str) -> Path:
        dest = self.resolve(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise StorageError("refusing to overwrite an existing stored file")
        os.replace(src, dest)
        return dest

    def prepare_job_output(self, job_id: str) -> Path:
        """Fresh, empty output directory for a job attempt (previous attempt's files removed)."""
        path = self.resolve(self.job_output_key(job_id))
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        return path

    def delete(self, key: str) -> None:
        path = self.resolve(key)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self.resolve(key).exists()

    def size(self, key: str) -> int:
        return self.resolve(key).stat().st_size

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.root).free

    def check_writable(self) -> None:
        probe = self.root / self.TEMPORARY / f".probe-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()

    def cleanup_temporary(self, max_age_seconds: float) -> int:
        """Delete stale partial uploads. Returns the number of files removed."""
        cutoff = time.time() - max_age_seconds
        removed = 0
        for p in (self.root / self.TEMPORARY).glob("*"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except OSError:
                continue
        return removed
