"""JSON / CSV / text exports. Schemas are documented in documentation/output_schema.md."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.core.exceptions import OutputWriteError
from app.pipeline.models import ProcessingResult, TrackObservation, WagonRecord

SCHEMA_VERSION = "1.0"

WAGON_CSV_COLUMNS = [
    "sequence_position",
    "wagon_uid",
    "class_name",
    "class_confidence",
    "class_best_guess",
    "class_distribution",
    "count_status",
    "uncertain",
    "flags",
    "first_seen_s",
    "last_seen_s",
    "reference_time_s",
    "crossing_time_s",
    "first_frame",
    "last_frame",
    "track_ids",
    "n_observations",
    "notes",
]

TRACK_CSV_COLUMNS = [
    "wagon_uid", "track_id", "frame_index", "sample_index", "timestamp_s",
    "x1", "y1", "x2", "y2", "class_name", "confidence", "touches_edge",
]


def _r(v: float | None, nd: int = 4) -> float | None:
    return None if v is None else round(float(v), nd)


def wagon_to_dict(w: WagonRecord, uncertain: bool) -> dict[str, Any]:
    d = w.class_decision
    return {
        "wagon_uid": w.wagon_uid,
        "sequence_position": w.sequence_position,
        "class_name": w.class_name,
        "class_confidence": d.confidence,
        "class_best_guess": d.best_guess,
        "class_runner_up": d.runner_up,
        "class_distribution": d.distribution,
        "class_uncertain": d.uncertain,
        "mean_detection_confidence": d.mean_detection_confidence,
        "supporting_observations": d.supporting_observations,
        "count_status": w.count_status.value,
        "uncertain": uncertain,
        "flags": sorted(f.value for f in w.flags),
        "notes": w.notes,
        "track_ids": w.track_ids,
        "n_observations": w.n_observations,
        "first_seen_s": _r(w.first_timestamp),
        "last_seen_s": _r(w.last_timestamp),
        "first_frame": w.first_frame,
        "last_frame": w.last_frame,
        "reference_time_s": _r(w.reference_time),
        "crossing_time_s": _r(w.crossing_time),
        "crossing_direction": w.crossing_direction,
        "velocity_px_per_s": w.mean_velocity,
    }


def result_to_dict(result: ProcessingResult) -> dict[str, Any]:
    from app.pipeline.sequence_builder import UNCERTAIN_FLAGS

    wagons_sorted = sorted(
        result.wagons, key=lambda w: (w.sequence_position is None, w.sequence_position or 0, w.wagon_uid)
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": result.run_id,
        "status": result.status,
        "error": result.error,
        "input": asdict(result.video) if result.video else None,
        "model": result.model,
        "config": result.config,
        "sampling": result.sampling,
        "timing_seconds": result.timing,
        "counts": asdict(result.counts) if result.counts else None,
        "sequence_info": result.sequence_info,
        "sequence": [asdict(s) for s in result.sequence],
        "wagons": [wagon_to_dict(w, bool(w.flags & UNCERTAIN_FLAGS)) for w in wagons_sorted],
        "warnings": result.warnings,
        "unresolved_identities": result.unresolved_identities,
        "artifacts": result.artifacts,
    }


def write_json(result: ProcessingResult, path: Path) -> None:
    try:
        path.write_text(json.dumps(result_to_dict(result), indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        raise OutputWriteError(f"Could not write {path.name}: {exc}") from exc


def write_wagons_csv(result: ProcessingResult, path: Path) -> None:
    rows = result_to_dict(result)["wagons"]
    try:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=WAGON_CSV_COLUMNS)
            writer.writeheader()
            for w in rows:
                writer.writerow({
                    "sequence_position": w["sequence_position"] if w["sequence_position"] is not None else "",
                    "wagon_uid": w["wagon_uid"],
                    "class_name": w["class_name"],
                    "class_confidence": w["class_confidence"],
                    "class_best_guess": w["class_best_guess"],
                    "class_distribution": "; ".join(f"{k}:{v}" for k, v in w["class_distribution"].items()),
                    "count_status": w["count_status"],
                    "uncertain": w["uncertain"],
                    "flags": ";".join(w["flags"]),
                    "first_seen_s": w["first_seen_s"],
                    "last_seen_s": w["last_seen_s"],
                    "reference_time_s": "" if w["reference_time_s"] is None else w["reference_time_s"],
                    "crossing_time_s": "" if w["crossing_time_s"] is None else w["crossing_time_s"],
                    "first_frame": w["first_frame"],
                    "last_frame": w["last_frame"],
                    "track_ids": ";".join(str(t) for t in w["track_ids"]),
                    "n_observations": w["n_observations"],
                    "notes": " | ".join(w["notes"]),
                })
    except OSError as exc:
        raise OutputWriteError(f"Could not write {path.name}: {exc}") from exc


def write_tracks_csv(observations: dict[str, list[TrackObservation]], path: Path) -> None:
    try:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(TRACK_CSV_COLUMNS)
            for uid in sorted(observations):
                for o in observations[uid]:
                    writer.writerow([
                        uid, o.track_id, o.frame_index, o.sample_index, round(o.timestamp, 4),
                        *(round(v, 1) for v in o.bbox), o.class_name, round(o.confidence, 4), o.touches_edge,
                    ])
    except OSError as exc:
        raise OutputWriteError(f"Could not write {path.name}: {exc}") from exc


def format_summary(result: ProcessingResult) -> str:
    lines = [f"Run {result.run_id}: {result.status}"]
    if result.error:
        lines.append(f"Error: {result.error}")
    if result.video:
        v = result.video
        lines.append(f"Input: {Path(v.path).name} {v.width}x{v.height} @ {v.fps or '?'} fps, "
                     f"{v.duration_seconds or 0:.1f}s, codec {v.codec or '?'}")
    if result.model:
        lines.append(f"Model: {result.model.get('model_file')} ({result.model.get('num_classes')} classes, "
                     f"device {result.model.get('device')})")
    if result.sampling:
        s = result.sampling
        lines.append(f"Sampling: {s.get('sampled_frames')} of {s.get('decoded_frames')} frames "
                     f"(target {s.get('target_fps')} fps, effective {s.get('effective_fps')} fps)")
    c = result.counts
    if c:
        lines.append(f"Counting mode: {c.mode}")
        lines.append(f"Total counted: {c.total_counted}  (wagons excluding {c.excluded_classes or 'none'}: "
                     f"{c.wagons_only_total})")
        lines.append(f"Records not counted: {c.not_counted}   Tracker IDs seen: {c.tracker_ids_seen}")
        if c.type_counts:
            width = max(len(k) for k in c.type_counts)
            lines.append("Type counts:")
            for k, n in c.type_counts.items():
                lines.append(f"  {k:<{width}}  {n}")
    if result.sequence_info:
        si = result.sequence_info
        lines.append(f"Sequence ({si.get('convention')}, {si.get('travel_direction')}, "
                     f"completeness: {si.get('completeness')}, uncertain items: {si.get('uncertain_items')}):")
        lines.append("  " + (si.get("order_string") or "(empty)"))
    if result.warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {w}" for w in result.warnings)
    if result.artifacts:
        lines.append(f"Outputs in {result.output_dir}:")
        lines.extend(f"  {k}: {v}" for k, v in result.artifacts.items())
    return "\n".join(lines)
