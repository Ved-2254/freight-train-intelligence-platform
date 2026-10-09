"""One-command launcher:  python -m app.serve   (from the backend/ directory)

Starts the API with uvicorn; with FTIP_START_EMBEDDED_WORKER=true (default) the API also starts
and supervises the background worker, so nothing else needs to be launched.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from app.core.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="python -m app.serve", description="Run the API (and embedded worker)")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes (development)")
    args = parser.parse_args(argv)
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=1,  # one API process: it owns the embedded worker
        log_level=settings.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
