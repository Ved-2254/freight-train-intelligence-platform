"""FastAPI application factory.

    uvicorn app.main:app            (API only; see app/serve.py for the one-command launcher)

The API never runs inference itself. With FTIP_START_EMBEDDED_WORKER=true (default) it starts
and supervises one `python -m app.workers` child process; otherwise run the worker separately.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.dependencies import build_container
from app.api.errors import install_error_handlers
from app.api.routes import health, jobs, videos
from app.core.logging import configure_logging, get_logger
from app.core.settings import ServiceSettings, get_settings
from app.pipeline.config import BACKEND_DIR
from app.services.links import API_PREFIX

log = get_logger("api")

DESCRIPTION = """
Backend for the freight-train wagon analysis pipeline.

**Workflow**
1. `POST /api/v1/videos` (multipart, field `file`) → `video_id`
2. `POST /api/v1/jobs` with `{"video_id": ...}` → `202` + `job_id` and `status_url`
3. Poll `GET /api/v1/jobs/{job_id}` every ~2 s until `status` is `completed`, `failed` or `cancelled`
4. `GET /api/v1/jobs/{job_id}/results`, `/video`, `/exports/json`, `/exports/csv`

Job statuses: `queued` → `running` → `completed` | `failed` | `cancelled`. All timestamps are UTC.
Errors always use `{"error": {"code", "message", "details"}, "request_id"}`.

⚠️ No authentication: intended for a trusted local/demo environment only.
"""


class RequestContextMiddleware:
    """Assigns/propagates X-Request-ID and logs one line per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")[:100]
        rid = incoming if incoming and incoming.replace("-", "").isalnum() else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid
        start = time.perf_counter()
        status_holder = {"status": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                hdrs = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                hdrs.append((b"x-request-id", rid.encode()))
                message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            log.info("%s %s -> %s (%.0f ms) rid=%s", scope["method"], scope["path"], status_holder["status"],
                     (time.perf_counter() - start) * 1000, rid)


class UploadSizeLimitMiddleware:
    """Rejects oversized uploads before/while the multipart body is parsed (413)."""

    def __init__(self, app, path: str, max_bytes: int):
        self.app = app
        self.path = path
        self.max_bytes = max_bytes
        self.slack = 1024 * 1024  # multipart framing overhead

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"].rstrip("/") != self.path:
            return await self.app(scope, receive, send)
        limit = self.max_bytes + self.slack
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            body = json.dumps({
                "error": {"code": "UPLOAD_TOO_LARGE",
                          "message": f"The upload exceeds the maximum size of {self.max_bytes} bytes",
                          "details": {"max_upload_bytes": self.max_bytes}},
                "request_id": scope.get("state", {}).get("request_id"),
            }).encode()
            await send({"type": "http.response.start", "status": 413,
                        "headers": [(b"content-type", b"application/json"), (b"connection", b"close")]})
            await send({"type": "http.response.body", "body": body})
            return
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    from fastapi import HTTPException

                    raise HTTPException(status_code=413, detail="UPLOAD_TOO_LARGE")
            return message

        await self.app(scope, limited_receive, send)


class EmbeddedWorker:
    """Starts `python -m app.workers` as a child process and restarts it if it crashes."""

    def __init__(self, settings: ServiceSettings, max_restarts: int = 5, window_seconds: float = 600.0):
        self.settings = settings
        self.proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.max_restarts = max_restarts
        self.window = window_seconds
        self._restarts: list[float] = []

    def _spawn(self) -> None:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        self.proc = subprocess.Popen([sys.executable, "-m", "app.workers"], cwd=str(BACKEND_DIR),
                                     creationflags=flags, env=self._child_env())
        log.info("Embedded worker started (pid %s)", self.proc.pid)

    def _child_env(self) -> dict[str, str]:
        """The worker must use exactly the API's effective settings (same database and storage)."""
        env = os.environ.copy()
        for name, value in self.settings.model_dump().items():
            key = f"FTIP_{name.upper()}"
            if value is None:
                env.pop(key, None)
            else:
                env[key] = str(value)
        return env

    def start(self) -> None:
        self._spawn()
        self._thread = threading.Thread(target=self._supervise, name="worker-supervisor", daemon=True)
        self._thread.start()

    def _supervise(self) -> None:
        while not self._stop.wait(2.0):
            if self.proc is None or self.proc.poll() is None:
                continue
            now = time.monotonic()
            self._restarts = [t for t in self._restarts if now - t < self.window]
            if len(self._restarts) >= self.max_restarts:
                log.error("Embedded worker exited %d times in %.0fs; not restarting. Start it manually with "
                          "`python -m app.workers`.", len(self._restarts), self.window)
                return
            log.warning("Embedded worker exited with code %s; restarting", self.proc.returncode)
            self._restarts.append(now)
            self._spawn()

    def stop(self) -> None:
        self._stop.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        log.info("Embedded worker stopped")


def create_app(settings: ServiceSettings | None = None, start_worker: bool | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    container = build_container(settings)
    run_worker = settings.start_embedded_worker if start_worker is None else start_worker

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container.storage.initialize()
        container.db.initialize()
        removed = container.storage.cleanup_temporary(settings.temporary_max_age_seconds)
        if removed:
            log.info("Removed %d stale temporary upload(s)", removed)
        worker = EmbeddedWorker(settings) if run_worker else None
        if worker:
            worker.start()
        log.info("API ready on %s (storage %s)", API_PREFIX, settings.storage_root.name)
        try:
            yield
        finally:
            if worker:
                worker.stop()

    app = FastAPI(
        title="Freight Train Intelligence Platform API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.container = container
    install_error_handlers(app)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(videos.router, prefix=API_PREFIX)
    app.include_router(jobs.router, prefix=API_PREFIX)

    # Outermost last: request context wraps everything, CORS applies to error responses too.
    app.add_middleware(UploadSizeLimitMiddleware, path=f"{API_PREFIX}/videos", max_bytes=settings.max_upload_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID", "Range"],
        expose_headers=["X-Request-ID", "Location", "Content-Disposition", "Content-Range", "Accept-Ranges",
                        "Content-Length", "Idempotent-Replayed"],
    )
    app.add_middleware(RequestContextMiddleware)
    return app


def __getattr__(name: str):
    # `uvicorn app.main:app` support without building the app at import time (tests use create_app).
    if name == "app":
        return create_app()
    raise AttributeError(name)
