"""Public (client-safe) views of pipeline results and artifacts.

The pipeline's result.json contains absolute server paths (input path, model path). The worker
stores a sanitised copy (`result.public.json`) once per job; the API serves only that copy.
Field meanings are unchanged; only path strings are reduced to their file names.
"""

from __future__ import annotations

import json
import re
from pathlib import PureWindowsPath, PurePosixPath
from typing import Any

# Windows drive paths (C:\... or C:/...) and UNC paths; POSIX absolute paths with 2+ segments.
_WIN_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\"'<>|\r\n]*")
_POSIX_PATH = re.compile(r"(?<![\w:/.])/(?:[^/\s\"'<>|]+/)+[^/\s\"'<>|]*")

# Artifact kinds produced by the pipeline -> (media type, exposed for download?)
ARTIFACT_KINDS: dict[str, tuple[str, bool]] = {
    "annotated_video": ("video/mp4", True),
    "result_json": ("application/json", False),  # raw, contains server paths
    "result_public_json": ("application/json", True),
    "wagons_csv": ("text/csv", True),
    "tracks_csv": ("text/csv", True),
    "summary": ("text/plain", False),  # contains server paths
    "log": ("text/plain", False),
}

# export format in the URL -> artifact kind, download filename suffix
EXPORT_FORMATS: dict[str, tuple[str, str]] = {
    "json": ("result_public_json", "result.json"),
    "csv": ("wagons_csv", "wagons.csv"),
    "tracks_csv": ("tracks_csv", "tracks.csv"),
}


def _basename(path: str) -> str:
    p = PureWindowsPath(path) if ("\\" in path or re.match(r"^[A-Za-z]:", path)) else PurePosixPath(path)
    return p.name or path


def scrub_paths(value: Any) -> Any:
    """Recursively replace absolute filesystem paths inside strings with their file names."""
    if isinstance(value, dict):
        return {k: scrub_paths(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_paths(v) for v in value]
    if isinstance(value, str):
        if "://" in value:  # URLs are not filesystem paths
            return value
        value = _WIN_PATH.sub(lambda m: _basename(m.group(0).rstrip(" .,;)")), value)
        return _POSIX_PATH.sub(lambda m: _basename(m.group(0)), value)
    return value


def public_result(raw: dict[str, Any], original_filename: str | None) -> dict[str, Any]:
    out = scrub_paths(raw)
    if original_filename and isinstance(out.get("input"), dict):
        out["input"]["path"] = original_filename
    return out


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    """Compact summary stored on the job row (for job lists / status polling)."""
    counts = result.get("counts") or {}
    seq = result.get("sequence_info") or {}
    out_video = (result.get("sampling") or {}).get("output_video") or {}
    codec = out_video.get("codec")
    return {
        "total_wagons": counts.get("wagons_only_total", 0),
        "total_rolling_stock": counts.get("total_counted", 0),
        "excluded_classes": counts.get("excluded_classes", []),
        "type_counts": counts.get("type_counts", {}),
        "not_counted": counts.get("not_counted", 0),
        "sequence_completeness": seq.get("completeness"),
        "uncertain_sequence_items": seq.get("uncertain_items"),
        "warnings": len(result.get("warnings") or []),
        "annotated_video_codec": codec,
        "browser_playable_video": None if codec is None else codec.lower() in ("avc1", "h264"),
    }


def load_json(path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
