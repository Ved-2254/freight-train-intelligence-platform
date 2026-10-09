"""API-relative (or absolute, when FTIP_PUBLIC_BASE_URL is set) resource links."""

from __future__ import annotations

API_PREFIX = "/api/v1"


class LinkBuilder:
    def __init__(self, public_base_url: str | None = None):
        self.base = (public_base_url or "").rstrip("/")

    def _u(self, path: str) -> str:
        return f"{self.base}{API_PREFIX}{path}"

    def video(self, video_id: str) -> str:
        return self._u(f"/videos/{video_id}")

    def jobs(self) -> str:
        return self._u("/jobs")

    def job(self, job_id: str) -> str:
        return self._u(f"/jobs/{job_id}")

    def cancel(self, job_id: str) -> str:
        return self._u(f"/jobs/{job_id}/cancel")

    def results(self, job_id: str) -> str:
        return self._u(f"/jobs/{job_id}/results")

    def annotated_video(self, job_id: str) -> str:
        return self._u(f"/jobs/{job_id}/video")

    def export(self, job_id: str, fmt: str) -> str:
        return self._u(f"/jobs/{job_id}/exports/{fmt}")
