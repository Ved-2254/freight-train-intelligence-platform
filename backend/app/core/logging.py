"""Logging setup shared by the CLI and (later) the worker."""

from __future__ import annotations

import logging
from pathlib import Path

LOGGER_NAME = "wagon"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class _ConsoleHandler(logging.StreamHandler):
    """Marker subclass so repeated configuration does not add duplicate console handlers."""


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def configure_logging(level: str = "INFO") -> None:
    """Console logging at `level`; the logger itself passes everything so file handlers can capture DEBUG."""
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(logging.DEBUG)
    root.propagate = False
    console = next((h for h in root.handlers if isinstance(h, _ConsoleHandler)), None)
    if console is None:
        console = _ConsoleHandler()
        console.setFormatter(logging.Formatter(_FORMAT, "%H:%M:%S"))
        root.addHandler(console)
    console.setLevel(level.upper())


def add_file_handler(path: Path, level: str = "DEBUG") -> logging.FileHandler:
    """Attach a per-run log file; caller must remove it with `remove_handler`."""
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(level.upper())
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    return handler


def remove_handler(handler: logging.Handler) -> None:
    logging.getLogger(LOGGER_NAME).removeHandler(handler)
    handler.close()
