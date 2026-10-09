"""Background worker: claims queued jobs from SQLite and runs the pipeline, one at a time.

One job per process: the pipeline's ByteTrack implementation uses a process-global track-ID
counter, and a single GPU should not run several inference jobs concurrently. More throughput
= more worker processes (claims are atomic, so they never run the same job twice).

Liveness: a heartbeat thread refreshes the worker row and the current job's `heartbeat_at`
every `heartbeat_seconds`. Any worker periodically recovers *stale* running jobs (no heartbeat
for `stale_job_seconds`): re-queued while attempts < max_attempts, otherwise failed with
WORKER_INTERRUPTED.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.exceptions import JobCancelledError
from app.core.ids import to_utc_string, utc_now
from app.core.logging import get_logger
from app.core.settings import ServiceSettings
from app.repositories.artifact_repository import ArtifactRecord
from app.repositories.database import Database
from app.repositories.job_repository import JobRecord, JobRepository, WorkerRepository
from app.repositories.video_repository import VideoRepository
from app.services.result_service import ARTIFACT_KINDS, load_json, public_result, summarize
from app.storage.file_storage import LocalFileStorage
from app.workers.pipeline_runner import PipelineRunner, RunContext, classify_error

log = get_logger("worker")

PUBLIC_RESULT_FILE = "result.public.json"


class VideoWorker:
    def __init__(
        self,
        settings: ServiceSettings,
        db: Database,
        storage: LocalFileStorage,
        runner: PipelineRunner,
        worker_id: str | None = None,
    ):
        self.settings = settings
        self.db = db
        self.storage = storage
        self.runner = runner
        self.jobs = JobRepository(db)
        self.videos = VideoRepository(db)
        self.workers = WorkerRepository(db)
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.started_at = utc_now()
        self.current_job_id: str | None = None
        self._last_recovery = 0.0

    # --------------------------------------------------------------- lifecycle
    def initialize(self) -> None:
        self.db.initialize()
        self.storage.initialize()
        self.recover_stale_jobs()

    def run_forever(self, stop: threading.Event) -> None:
        self.initialize()
        hb_stop = threading.Event()
        hb = threading.Thread(target=self._heartbeat_loop, args=(hb_stop,), name="worker-heartbeat", daemon=True)
        hb.start()
        log.info("Worker %s started (poll %.1fs)", self.worker_id, self.settings.worker_poll_seconds)
        try:
            while not stop.is_set():
                if time.monotonic() - self._last_recovery > self.settings.heartbeat_seconds:
                    self.recover_stale_jobs()
                try:
                    worked = self.run_once()
                except Exception:  # never let one bad job kill the worker loop
                    log.exception("Unexpected worker error")
                    worked = False
                if not worked:
                    stop.wait(self.settings.worker_poll_seconds)
        finally:
            hb_stop.set()
            hb.join(timeout=5)
            try:
                self.workers.remove(self.worker_id)
            except Exception:
                pass
            log.info("Worker %s stopped", self.worker_id)

    def _heartbeat_loop(self, stop: threading.Event) -> None:
        host, pid = socket.gethostname(), os.getpid()
        while not stop.is_set():
            try:
                self.workers.beat(self.worker_id, host, pid, self.started_at, self.current_job_id)
                if self.current_job_id:
                    self.jobs.heartbeat(self.current_job_id)
            except Exception:
                log.warning("Heartbeat failed", exc_info=True)
            stop.wait(self.settings.heartbeat_seconds)

    def recover_stale_jobs(self) -> list[tuple[str, str]]:
        self._last_recovery = time.monotonic()
        now = datetime.now(timezone.utc)
        cutoff = to_utc_string(now - timedelta(seconds=self.settings.stale_job_seconds))
        # A worker that missed 3 heartbeats is dead; its running job can be recovered early.
        dead = to_utc_string(now - timedelta(seconds=self.settings.heartbeat_seconds * 3))
        recovered = self.jobs.recover_stale(cutoff, self.settings.max_attempts, dead_worker_before=dead)
        for job_id, status in recovered:
            log.warning("Recovered interrupted job %s -> %s", job_id, status)
        return recovered

    # ------------------------------------------------------------------- jobs
    def run_once(self) -> bool:
        """Claim and process one job. Returns False when the queue is empty."""
        job = self.jobs.claim_next(self.worker_id)
        if job is None:
            return False
        self.current_job_id = job.job_id
        try:
            self.process(job)
        finally:
            self.current_job_id = None
        return True

    def process(self, job: JobRecord) -> None:
        log.info("Processing job %s (video %s, attempt %d)", job.job_id, job.video_id, job.attempts)
        video = self.videos.get(job.video_id)
        if video is None or video.status != "ready" or not self.storage.exists(video.storage_key):
            self.jobs.fail(job.job_id, "VIDEO_NOT_AVAILABLE", "The source video is no longer available", None)
            return
        if job.cancel_requested:
            self.jobs.mark_cancelled(job.job_id, "Cancelled before processing started")
            return

        out_dir = self.storage.prepare_job_output(job.job_id)
        ctx = RunContext(
            job_id=job.job_id,
            input_path=self.storage.resolve(video.storage_key),
            output_dir=out_dir,
            options=job.options,
            on_progress=self._progress_writer(job.job_id),
            should_cancel=self._cancel_checker(job.job_id),
        )
        try:
            result, config = self.runner.run(ctx)
        except JobCancelledError:
            log.info("Job %s cancelled during processing", job.job_id)
            self.jobs.mark_cancelled(job.job_id, "Cancelled during processing")
            return
        except BaseException as exc:  # noqa: BLE001 - every failure must be recorded
            code, message = classify_error(exc)
            if code == "INTERNAL_ERROR":
                log.exception("Job %s failed unexpectedly", job.job_id)
            else:
                log.error("Job %s failed (%s): %s", job.job_id, code, exc)
            internal = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.jobs.fail(job.job_id, code, message, internal[:4000])
            if not isinstance(exc, Exception):
                raise  # KeyboardInterrupt / SystemExit: stop after recording
            return

        try:
            self._record_success(job, video.original_filename, out_dir, result, config)
        except Exception as exc:
            log.exception("Job %s: could not record results", job.job_id)
            self.jobs.fail(job.job_id, "OUTPUT_WRITE_FAILED", "The results could not be saved on the server", repr(exc)[:4000])

    def _record_success(self, job: JobRecord, original_filename: str, out_dir: Path, result, config) -> None:
        raw = load_json(out_dir / "result.json")
        public = public_result(raw, original_filename)
        public_path = out_dir / PUBLIC_RESULT_FILE
        public_path.write_text(json.dumps(public, indent=2, ensure_ascii=False), encoding="utf-8")

        files = dict(result.artifacts)
        files["result_public_json"] = PUBLIC_RESULT_FILE
        now = utc_now()
        artifacts = []
        for kind, rel in sorted(files.items()):
            path = out_dir / rel
            if kind not in ARTIFACT_KINDS or not path.is_file():
                continue
            artifacts.append(ArtifactRecord(
                job_id=job.job_id, kind=kind, storage_key=self.storage.key_for(path),
                size_bytes=path.stat().st_size, media_type=ARTIFACT_KINDS[kind][0], created_at=now,
            ))
        model = public.get("model") or {}
        ok = self.jobs.complete(job.job_id, summarize(public), public.get("config") or {}, model, artifacts)
        if ok:
            log.info("Job %s completed: %s wagons", job.job_id, summarize(public)["total_wagons"])
        else:
            log.warning("Job %s finished but was no longer running (state changed concurrently)", job.job_id)

    # ---------------------------------------------------------------- helpers
    def _progress_writer(self, job_id: str):
        interval = self.settings.progress_write_interval
        state = {"last": 0.0, "stage": None}

        def write(stage: str, percent: float | None, message: str) -> None:
            now = time.monotonic()
            if stage == state["stage"] and now - state["last"] < interval:
                return  # throttle DB writes; stage changes are always written
            state["last"], state["stage"] = now, stage
            try:
                self.jobs.update_progress(job_id, stage, percent, message)
            except Exception:
                log.warning("Progress update failed for %s", job_id, exc_info=True)

        return write

    def _cancel_checker(self, job_id: str):
        interval = self.settings.cancel_check_interval
        state = {"last": 0.0, "value": False}

        def check() -> bool:
            now = time.monotonic()
            if not state["value"] and now - state["last"] >= interval:
                state["last"] = now
                try:
                    state["value"] = self.jobs.is_cancel_requested(job_id)
                except Exception:
                    log.warning("Cancel check failed for %s", job_id, exc_info=True)
            return state["value"]

        return check
