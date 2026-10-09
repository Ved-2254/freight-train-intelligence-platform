"""Travel-direction estimation, reference-line timing and wagon sequencing.

Sequence convention ("passage_order_at_reference_line"):
  Wagons are ordered by the time their box centre passes a reference line placed across the
  travel axis (`counting.line_position`, default mid-frame). Position 1 is the first wagon to
  pass the line, i.e. the leading end of the train *in its direction of travel*. Whether that
  end is the physical front (locomotive pulling) or rear (pushing) cannot be determined from
  the video and is not claimed. If the train stops or reverses, the order is flagged uncertain.

When a wagon was never observed crossing the line (cut off by the start/end of the recording,
or lost early), its crossing time is extrapolated from its fitted motion and flagged
`sequence_extrapolated`. A stationary scene falls back to spatial order along the travel axis.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

from app.core.logging import get_logger
from app.pipeline import geometry, motion
from app.pipeline.config import CountingConfig, ResolutionConfig
from app.pipeline.models import SequenceItem, TrackObservation, WagonFlag, WagonRecord

log = get_logger("sequence")

UNCERTAIN_FLAGS = {
    WagonFlag.CLASS_UNCERTAIN,
    WagonFlag.AMBIGUOUS_IDENTITY,
    WagonFlag.DUPLICATE_CANDIDATE,
    WagonFlag.POSSIBLE_ID_SWITCH,
    WagonFlag.SEQUENCE_EXTRAPOLATED,
    WagonFlag.DIRECTION_INCONSISTENT,
}


@dataclass
class MotionSummary:
    axis: str  # "x" | "y"
    direction: int  # +1, -1, or 0 (stationary / unknown)
    direction_label: str
    reference_position: float  # pixels along the axis
    inconsistent_wagons: list[str]
    moving_wagons: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "travel_axis": self.axis,
            "travel_direction": self.direction_label,
            "reference_line_px": round(self.reference_position, 1),
            "moving_wagons": self.moving_wagons,
            "direction_inconsistent_wagons": self.inconsistent_wagons,
        }


def _axis_values(obs: list[TrackObservation], axis: str) -> list[float]:
    i = 0 if axis == "x" else 1
    return [o.center[i] for o in obs]


def _direction_label(axis: str, direction: int) -> str:
    if direction == 0:
        return "stationary_or_unknown"
    if axis == "x":
        return "left_to_right" if direction > 0 else "right_to_left"
    return "top_to_bottom" if direction > 0 else "bottom_to_top"


def analyze_motion(
    wagons: list[WagonRecord],
    observations: dict[str, list[TrackObservation]],
    frame_size: tuple[int, int],
    counting: CountingConfig,
    resolution: ResolutionConfig,
    video_span: tuple[float, float] | None = None,
    edge_margin: float = 4.0,
) -> MotionSummary:
    """Estimate travel axis/direction, fill reference/crossing times and partial-observation flags.

    Velocities are measured on unclipped box edges (see motion.py), so wagons entering or
    leaving the frame do not bias speed/direction estimates.
    """
    width, height = frame_size
    velocities: dict[str, tuple[float, float]] = {
        w.wagon_uid: motion.velocity(observations[w.wagon_uid], frame_size, edge_margin) for w in wagons
    }

    evidence = [w for w in wagons if w.counted] or wagons
    if counting.travel_axis != "auto":
        axis = counting.travel_axis
    elif evidence:
        mx = median(abs(velocities[w.wagon_uid][0]) for w in evidence)
        my = median(abs(velocities[w.wagon_uid][1]) for w in evidence)
        axis = "x" if mx >= my else "y"
    else:
        axis = "x"
    ai = 0 if axis == "x" else 1
    ref = counting.line_position * (width if axis == "x" else height)

    moving = [w for w in evidence if abs(velocities[w.wagon_uid][ai]) >= resolution.min_speed_px_per_s]
    if counting.expected_direction != "auto":
        direction = 1 if counting.expected_direction == "positive" else -1
    elif moving:
        med = median(velocities[w.wagon_uid][ai] for w in moving)
        direction = 1 if med > 0 else -1
    else:
        direction = 0

    inconsistent: list[str] = []
    for w in wagons:
        v = velocities[w.wagon_uid][ai]
        w.mean_velocity = round(v, 3)
        obs = observations[w.wagon_uid]
        if direction != 0 and abs(v) >= resolution.min_speed_px_per_s and (v > 0) != (direction > 0):
            w.flags.add(WagonFlag.DIRECTION_INCONSISTENT)
            inconsistent.append(w.wagon_uid)
        w.crossing_time, w.crossing_direction = _validated_crossing(obs, axis, ref, counting.hysteresis_px, direction)
        if w.crossing_time is not None:
            w.reference_time = w.crossing_time
        else:
            w.reference_time = _extrapolated_crossing(obs, axis, ref, v, frame_size, edge_margin)
            if direction != 0:
                w.flags.add(WagonFlag.SEQUENCE_EXTRAPOLATED)
        if video_span is not None:
            _partial_flags(w, obs, axis, direction, video_span, counting.boundary_seconds, frame_size, edge_margin)

    summary = MotionSummary(axis, direction, _direction_label(axis, direction), ref, inconsistent, len(moving))
    log.info("Motion: axis=%s direction=%s, %d moving wagons, %d inconsistent",
             axis, summary.direction_label, len(moving), len(inconsistent))
    return summary


def _partial_flags(
    w: WagonRecord,
    obs: list[TrackObservation],
    axis: str,
    direction: int,
    video_span: tuple[float, float],
    boundary: float,
    frame_size: tuple[int, int],
    margin: float,
) -> None:
    """Flag wagons whose passage was cut by the start/end of the recording.

    With a known direction: partial at start = already inside the view (not at the entry edge)
    when first seen near the video start; partial at end = not yet at the exit edge when last
    seen near the video end. Without a direction only the timing rule applies.
    """
    start, end = video_span
    first, last = obs[0], obs[-1]
    near_start = first.timestamp - start <= boundary
    near_end = end - last.timestamp <= boundary
    if direction == 0:
        at_entry_first = at_exit_last = False
    else:
        lo_f, hi_f = motion.axis_clipping(first, axis, frame_size, margin)
        lo_l, hi_l = motion.axis_clipping(last, axis, frame_size, margin)
        at_entry_first = lo_f if direction > 0 else hi_f
        at_exit_last = hi_l if direction > 0 else lo_l
    if near_start and not at_entry_first:
        w.flags.add(WagonFlag.PARTIAL_AT_START)
    if near_end and not at_exit_last:
        w.flags.add(WagonFlag.PARTIAL_AT_END)


def _validated_crossing(
    obs: list[TrackObservation], axis: str, ref: float, hysteresis: float, direction: int
) -> tuple[float | None, int | None]:
    """First crossing of `ref` in the travel direction, with hysteresis against jitter.

    The centre must be observed beyond `ref - hysteresis` on the approach side and later beyond
    `ref + hysteresis` on the far side. Returns (interpolated time at ref, crossing sign).
    """
    if direction == 0 or len(obs) < 2:
        return None, None
    vals = _axis_values(obs, axis)
    armed = False
    last_before: int | None = None  # last observation strictly before the line
    for i, v in enumerate(vals):
        d = (v - ref) * direction  # negative = before the line along the travel direction
        if d < 0:
            last_before = i
            if d <= -hysteresis:
                armed = True
        elif d >= hysteresis and armed and last_before is not None:
            j = last_before
            t = geometry.interpolate_crossing(obs[j].timestamp, vals[j], obs[i].timestamp, v, ref)
            return t, direction
    return None, None


def _extrapolated_crossing(
    obs: list[TrackObservation], axis: str, ref: float, velocity: float,
    frame_size: tuple[int, int], margin: float,
) -> float | None:
    """Estimate when the box centre would pass `ref`, using only unclipped observations if possible."""
    free = motion.unclipped_on_axis(obs, axis, frame_size, margin)
    if len(free) >= 2:
        fit = geometry.linear_fit([o.timestamp for o in free], _axis_values(free, axis))
        if fit is not None:
            t = geometry.crossing_time_from_fit(fit, ref)
            if t is not None:
                return t
    if abs(velocity) < 1e-9:
        return None
    if free:
        o = free[-1]
        centre = _axis_values([o], axis)[0]
    else:
        # Every box is cut by the border: estimate the centre from the free edge and the
        # largest extent seen (a lower bound on the true wagon length).
        o = obs[-1]
        i = 0 if axis == "x" else 1
        extent = max((p.bbox[i + 2] - p.bbox[i]) for p in obs)
        lo_clip, hi_clip = motion.axis_clipping(o, axis, frame_size, margin)
        if lo_clip and not hi_clip:
            centre = o.bbox[i + 2] - extent / 2
        elif hi_clip and not lo_clip:
            centre = o.bbox[i] + extent / 2
        else:
            centre = _axis_values([o], axis)[0]
    return o.timestamp + (ref - centre) / velocity


def build_sequence(
    wagons: list[WagonRecord],
    observations: dict[str, list[TrackObservation]],
    motion: MotionSummary,
    counting: CountingConfig,
) -> tuple[list[SequenceItem], dict[str, Any]]:
    """Order counted wagons; returns (sequence, sequence_info)."""
    counted = [w for w in wagons if w.counted]
    ai = 0 if motion.axis == "x" else 1

    if motion.direction == 0:
        convention = "spatial_order_along_axis"

        def key(w: WagonRecord) -> tuple:
            obs = observations[w.wagon_uid]
            mean_pos = sum(o.center[ai] for o in obs) / len(obs)
            return (mean_pos, w.first_timestamp, w.wagon_uid)
    elif counting.mode == "line":
        convention = "line_crossing_order"

        def key(w: WagonRecord) -> tuple:
            return (w.crossing_time if w.crossing_time is not None else float("inf"), w.first_timestamp, w.wagon_uid)
    else:
        convention = "passage_order_at_reference_line"

        def key(w: WagonRecord) -> tuple:
            t = w.reference_time if w.reference_time is not None else w.first_timestamp
            return (t, w.first_timestamp, w.wagon_uid)

    ordered = sorted(counted, key=key)
    sequence: list[SequenceItem] = []
    for pos, w in enumerate(ordered, start=1):
        w.sequence_position = pos
        flags = sorted(f.value for f in w.flags)
        sequence.append(SequenceItem(
            position=pos,
            wagon_uid=w.wagon_uid,
            class_name=w.class_name,
            class_confidence=w.class_decision.confidence,
            reference_time=None if w.reference_time is None else round(w.reference_time, 4),
            crossing_time=None if w.crossing_time is None else round(w.crossing_time, 4),
            first_seen=round(w.first_timestamp, 4),
            uncertain=bool(w.flags & UNCERTAIN_FLAGS),
            flags=flags,
        ))

    starts = any(WagonFlag.PARTIAL_AT_START in w.flags for w in counted)
    ends = any(WagonFlag.PARTIAL_AT_END in w.flags for w in counted)
    completeness = {
        (False, False): "complete",
        (True, False): "partial_start",
        (False, True): "partial_end",
        (True, True): "partial_both",
    }[(starts, ends)]
    if not counted:
        completeness = "empty"

    notes = []
    if motion.direction == 0:
        notes.append("No consistent motion detected; sequence is spatial order along the travel axis, not passage order.")
    else:
        notes.append(
            "Position 1 is the first wagon to pass the reference line, i.e. the leading end in the direction of travel. "
            "Whether this is the physical front (pulling) or rear (pushing) of the train is not determined."
        )
    if completeness != "complete" and counted:
        notes.append("Wagons were already visible at the start and/or still visible at the end of the video; "
                     "the train may extend beyond the recording.")
    if motion.inconsistent_wagons:
        notes.append("Some wagons moved against the dominant direction (stop/reverse or tracking error); order is uncertain.")

    info = {
        "convention": convention,
        "completeness": completeness,
        "uncertain_items": sum(1 for s in sequence if s.uncertain),
        "order_string": " -> ".join(s.class_name for s in sequence),
        "notes": notes,
        **motion.to_dict(),
    }
    return sequence, info
