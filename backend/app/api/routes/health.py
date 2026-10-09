from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import __version__
from app.api.dependencies import Container, get_container
from app.core.ids import to_utc_string
from app.pipeline.config import load_config

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness: the API process is responding")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": __version__}


@router.get(
    "/ready",
    summary="Readiness: database, storage, disk space and model file are available",
    responses={503: {"description": "One or more required checks failed (see `checks`)"}},
)
def ready(c: Container = Depends(get_container)) -> JSONResponse:
    s = c.settings
    checks: dict[str, dict[str, Any]] = {}

    def check(name: str, fn) -> None:
        try:
            extra = fn() or {}
            checks[name] = {"ok": True, **extra}
        except Exception:  # details go to logs, not to clients
            checks[name] = {"ok": False}

    check("database", c.db.ping)
    check("storage_writable", c.storage.check_writable)

    def disk() -> dict[str, Any]:
        free = c.storage.free_bytes()
        if free < s.min_free_disk_bytes:
            raise RuntimeError("low disk")
        return {"free_bytes": free}

    check("disk_space", disk)

    def model() -> dict[str, Any]:
        path = load_config(s.pipeline_config).resolved_model_path()
        if not path.is_file():
            raise FileNotFoundError("model missing")
        return {"model_file": path.name}

    check("model_file", model)

    worker: dict[str, Any] = {"alive": False, "count": 0}
    try:
        cutoff = to_utc_string(datetime.now(timezone.utc) - timedelta(seconds=s.heartbeat_seconds * 3))
        alive = c.workers.alive_since(cutoff)
        worker = {"alive": bool(alive), "count": len(alive), "busy": sum(1 for r in alive if r["current_job_id"])}
    except Exception:
        pass

    ok = all(v["ok"] for v in checks.values())
    body = {
        "status": "ready" if ok else "not_ready",
        "checks": checks,
        # Informational: jobs are accepted and queued even while no worker is running.
        "worker": worker,
    }
    return JSONResponse(status_code=200 if ok else 503, content=body)
