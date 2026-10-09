"""Service (API + worker) settings, read from environment variables and `backend/.env`.

All variables use the `FTIP_` prefix, e.g. `FTIP_PORT=8000`. See `backend/.env.example`.
Pipeline/model settings are NOT duplicated here: they stay in `backend/configs/default.yaml`
(override the file with FTIP_PIPELINE_CONFIG).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.pipeline.config import BACKEND_DIR

GiB = 1024**3


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FTIP_", env_file=str(BACKEND_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # HTTP
    host: str = "127.0.0.1"
    port: int = Field(8000, ge=1, le=65535)
    cors_origins: str = "http://localhost:3000"  # comma-separated; never "*" by default
    public_base_url: str | None = None  # e.g. https://api.example.com -> absolute links
    log_level: str = "INFO"

    # Storage / database (relative paths resolve against backend/)
    storage_root: Path = Path("storage")
    database_path: Path | None = None  # default: <storage_root>/app.db
    max_upload_bytes: int = Field(2 * GiB, ge=1)
    allowed_extensions: str = ".mp4,.mov,.avi,.mkv"
    min_free_disk_bytes: int = Field(1 * GiB, ge=0)
    temporary_max_age_seconds: int = Field(24 * 3600, ge=60)

    # Pipeline
    pipeline_config: Path | None = None  # default: backend/configs/default.yaml

    # Worker
    start_embedded_worker: bool = True  # API starts/supervises `python -m app.workers` itself
    worker_poll_seconds: float = Field(1.0, gt=0)
    heartbeat_seconds: float = Field(5.0, gt=0)
    stale_job_seconds: float = Field(60.0, gt=0)  # running job without heartbeat -> interrupted
    max_attempts: int = Field(2, ge=1)  # 2 = an interrupted job is re-queued once
    progress_write_interval: float = Field(0.5, ge=0)
    cancel_check_interval: float = Field(0.5, ge=0)

    @field_validator("storage_root", "database_path", "pipeline_config", mode="after")
    @classmethod
    def _absolute(cls, v: Path | None) -> Path | None:
        if v is None:
            return None
        v = v.expanduser()
        return v if v.is_absolute() else (BACKEND_DIR / v).resolve()

    @property
    def db_path(self) -> Path:
        return self.database_path or self.storage_root / "app.db"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def extension_list(self) -> list[str]:
        exts = [e.strip().lower() for e in self.allowed_extensions.split(",") if e.strip()]
        return [e if e.startswith(".") else f".{e}" for e in exts]


@lru_cache
def get_settings() -> ServiceSettings:
    return ServiceSettings()
