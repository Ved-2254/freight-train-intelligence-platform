"""Small, pure geometric helpers used by the track manager, registry and sequencer."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from app.pipeline.models import BBox


def area(b: BBox) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a: BBox, b: BBox) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def iou(a: BBox, b: BBox) -> float:
    inter = intersection(a, b)
    union = area(a) + area(b) - inter
    return inter / union if union > 0 else 0.0


def containment(a: BBox, b: BBox) -> float:
    """Fraction of the smaller box covered by the other (1.0 = one box inside the other)."""
    smaller = min(area(a), area(b))
    return intersection(a, b) / smaller if smaller > 0 else 0.0


def touches_edge(b: BBox, width: int, height: int, margin: float) -> bool:
    return b[0] <= margin or b[1] <= margin or b[2] >= width - margin or b[3] >= height - margin


def clip_box(b: Sequence[float], width: int, height: int) -> BBox:
    x1, y1, x2, y2 = (float(v) for v in b)
    return (
        min(max(x1, 0.0), float(width)),
        min(max(y1, 0.0), float(height)),
        min(max(x2, 0.0), float(width)),
        min(max(y2, 0.0), float(height)),
    )


def linear_fit(times: Sequence[float], values: Sequence[float]) -> tuple[float, float] | None:
    """Least-squares fit value = slope * t + intercept. Returns None if under-determined."""
    t = np.asarray(times, dtype=float)
    v = np.asarray(values, dtype=float)
    if t.size < 2 or float(np.ptp(t)) <= 1e-9:
        return None
    slope, intercept = np.polyfit(t, v, 1)
    return float(slope), float(intercept)


def crossing_time_from_fit(fit: tuple[float, float], position: float) -> float | None:
    slope, intercept = fit
    if abs(slope) < 1e-9:
        return None
    return (position - intercept) / slope


def interpolate_crossing(t0: float, p0: float, t1: float, p1: float, position: float) -> float:
    """Time at which a point moving linearly from (t0,p0) to (t1,p1) reaches `position`."""
    if p1 == p0:
        return t0
    return t0 + (position - p0) * (t1 - t0) / (p1 - p0)
