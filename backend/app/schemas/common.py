"""Shared API schemas. All timestamps are UTC (ISO-8601, 'Z' suffix)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable, machine-readable error code, e.g. JOB_NOT_FOUND")
    message: str = Field(description="Human-readable, user-safe message")
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str | None = Field(None, description="Echoed X-Request-ID; quote it when reporting problems")


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses=` entries documenting the standard error body."""
    return {s: {"model": ErrorResponse} for s in statuses}
