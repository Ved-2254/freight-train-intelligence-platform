"""Wagon counting from resolved wagon records (never from raw detections or tracker IDs).

Modes:
  * registry - every wagon record with sufficient evidence is counted once.
  * line     - additionally requires a validated crossing of the reference line in the travel
               direction (see sequence_builder.analyze_motion, which must run first).

Type counts include the unresolved-class bucket, so sum(type_counts) == total_counted.
"""

from __future__ import annotations

from collections import Counter

from app.core.logging import get_logger
from app.pipeline.config import CountingConfig
from app.pipeline.models import CountResult, CountStatus, WagonRecord

log = get_logger("counter")


def apply_line_counting(wagons: list[WagonRecord]) -> None:
    """In line mode, records without a validated crossing are not counted (but stay reported)."""
    for w in wagons:
        if w.count_status == CountStatus.COUNTED and w.crossing_time is None:
            w.count_status = CountStatus.NOT_COUNTED_NO_LINE_CROSSING
            w.notes.append("no validated crossing of the counting line in the travel direction")


def calculate_counts(wagons: list[WagonRecord], counting: CountingConfig, tracker_ids_seen: int) -> CountResult:
    counted = [w for w in wagons if w.counted]
    type_counts = Counter(w.class_name for w in counted)
    excluded = set(counting.exclude_from_wagon_total)
    result = CountResult(
        mode=counting.mode,
        total_counted=len(counted),
        wagons_only_total=sum(1 for w in counted if w.class_name not in excluded),
        excluded_classes=sorted(excluded),
        type_counts=dict(sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        not_counted=len(wagons) - len(counted),
        tracker_ids_seen=tracker_ids_seen,
    )
    if sum(result.type_counts.values()) != result.total_counted:  # integrity guard
        raise AssertionError("type counts do not reconcile with the total")
    log.info("Counted %d wagons (%d records not counted) from %d tracker IDs",
             result.total_counted, result.not_counted, tracker_ids_seen)
    return result
