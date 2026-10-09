"""Clipping-aware motion estimation.

A wagon entering or leaving the frame produces a box that is cut off at the border; its
centre then moves at roughly half the true speed. Motion is therefore measured on box edges
that are not clipped: the centre when both edges are free, otherwise the free edge.
"""

from __future__ import annotations

from statistics import median
from typing import Sequence

from app.pipeline.models import TrackObservation

FrameSize = tuple[int, int] | None  # None = unknown frame size: treat no box as clipped

AXES = ("x", "y")


def axis_clipping(o: TrackObservation, axis: str, frame_size: FrameSize, margin: float) -> tuple[bool, bool]:
    """Whether the box touches the low (left/top) and high (right/bottom) border on this axis."""
    if frame_size is None:
        return False, False
    lo, hi = (o.bbox[0], o.bbox[2]) if axis == "x" else (o.bbox[1], o.bbox[3])
    limit = frame_size[0] if axis == "x" else frame_size[1]
    return lo <= margin, hi >= limit - margin


def _coords(o: TrackObservation, axis: str) -> tuple[float, float]:
    return (o.bbox[0], o.bbox[2]) if axis == "x" else (o.bbox[1], o.bbox[3])


def common_anchor(p: TrackObservation, q: TrackObservation, axis: str, frame_size: FrameSize,
                  margin: float) -> tuple[float, float] | None:
    """Return comparable positions of p and q on `axis` using only edges unclipped in both."""
    pl, ph = axis_clipping(p, axis, frame_size, margin)
    ql, qh = axis_clipping(q, axis, frame_size, margin)
    (p1, p2), (q1, q2) = _coords(p, axis), _coords(q, axis)
    low_ok, high_ok = not (pl or ql), not (ph or qh)
    if low_ok and high_ok:
        return (p1 + p2) / 2, (q1 + q2) / 2
    if low_ok:
        return p1, q1
    if high_ok:
        return p2, q2
    return None


def axis_velocity(obs: Sequence[TrackObservation], axis: str, frame_size: FrameSize, margin: float) -> float | None:
    """Median per-step velocity (px/s) on unclipped anchors; None if it cannot be measured."""
    rates = []
    for p, q in zip(obs, obs[1:]):
        dt = q.timestamp - p.timestamp
        if dt <= 0:
            continue
        pair = common_anchor(p, q, axis, frame_size, margin)
        if pair is not None:
            rates.append((pair[1] - pair[0]) / dt)
    return median(rates) if rates else None


def velocity(obs: Sequence[TrackObservation], frame_size: FrameSize, margin: float) -> tuple[float, float]:
    vx = axis_velocity(obs, "x", frame_size, margin)
    vy = axis_velocity(obs, "y", frame_size, margin)
    return (vx or 0.0, vy or 0.0)


def unclipped_on_axis(obs: Sequence[TrackObservation], axis: str, frame_size: FrameSize,
                      margin: float) -> list[TrackObservation]:
    return [o for o in obs if not any(axis_clipping(o, axis, frame_size, margin))]
