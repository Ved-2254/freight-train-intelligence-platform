"""Run the background worker:  python -m app.workers   (from the backend/ directory)."""

from __future__ import annotations

import argparse
import signal
import sys
import threading

from app.core.logging import configure_logging, get_logger
from app.core.settings import get_settings
from app.repositories.database import Database
from app.storage.file_storage import LocalFileStorage
from app.workers.pipeline_runner import PipelineRunner
from app.workers.video_worker import VideoWorker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.workers", description="Freight wagon job worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job, then exit")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("worker")
    worker = VideoWorker(settings, Database(settings.db_path), LocalFileStorage(settings.storage_root),
                         PipelineRunner(settings))
    if args.once:
        worker.initialize()
        worked = worker.run_once()
        log.info("Processed a job" if worked else "No queued job")
        return 0

    stop = threading.Event()

    def _stop(signum, _frame):  # Ctrl+C / terminate: finish the poll loop
        log.info("Signal %s received; stopping after the current step", signum)
        stop.set()
        if worker.current_job_id is not None:
            # A running inference job cannot be paused; exit now and let recovery re-queue it.
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)
    try:
        worker.run_forever(stop)
    except KeyboardInterrupt:
        log.warning("Worker interrupted during a job; it will be re-queued or failed by recovery")
    return 0


if __name__ == "__main__":
    sys.exit(main())
