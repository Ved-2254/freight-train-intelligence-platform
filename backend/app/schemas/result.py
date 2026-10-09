from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.job import JobLinks, JobResultSummary


class JobResultsResponse(BaseModel):
    job_id: str
    video_id: str
    status: str
    summary: JobResultSummary
    result: dict[str, Any] = Field(
        description=(
            "The pipeline's result.json (schema_version 1.0, see documentation/output_schema.md) with "
            "server filesystem paths replaced by file names. Field meanings are unchanged."
        )
    )
    links: JobLinks
