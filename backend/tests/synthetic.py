"""Deterministic synthetic data for tests: a train of boxes moving across the frame."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.pipeline.models import BBox, Detection, TrackObservation, TrackRecord, TrackState


@dataclass
class SyntheticTrain:
    """Wagon k occupies x in [lead_x(t) - k*(w+gap) - w, lead_x(t) - k*(w+gap)], moving +x."""

    classes: list[str]
    frame_size: tuple[int, int] = (640, 360)
    wagon_width: float = 150.0
    wagon_height: float = 120.0
    gap: float = 20.0
    speed: float = 200.0  # px/s, left to right
    start_x: float = -10.0  # leading edge position at t=0
    y_top: float = 120.0
    hidden: dict[int, list[tuple[float, float]]] = field(default_factory=dict)  # wagon -> [(t0,t1)] not detected

    def box(self, k: int, t: float) -> BBox | None:
        right = self.start_x + self.speed * t - k * (self.wagon_width + self.gap)
        left = right - self.wagon_width
        w, h = self.frame_size
        if right <= 0 or left >= w:
            return None
        return (max(0.0, left), self.y_top, min(float(w), right), self.y_top + self.wagon_height)

    def is_hidden(self, k: int, t: float) -> bool:
        return any(t0 <= t <= t1 for t0, t1 in self.hidden.get(k, []))

    def duration_to_clear(self) -> float:
        total_len = len(self.classes) * (self.wagon_width + self.gap)
        return (self.frame_size[0] + total_len - self.start_x) / self.speed


class ScriptedDetector:
    """Detector returning the synthetic train's boxes (with optional per-wagon label noise)."""

    def __init__(self, train: SyntheticTrain, class_names: dict[int, str], noise: dict[tuple[int, int], str] | None = None):
        self.train = train
        self.class_names = class_names
        self._ids = {v: k for k, v in class_names.items()}
        self.noise = noise or {}  # (wagon index, frame_index) -> wrong class name
        self.calls = 0

    def detect(self, image: np.ndarray, frame_index: int, timestamp: float) -> list[Detection]:
        self.calls += 1
        out = []
        for k, cls in enumerate(self.train.classes):
            b = self.train.box(k, timestamp)
            if b is None or b[2] - b[0] < 8 or self.train.is_hidden(k, timestamp):
                continue
            name = self.noise.get((k, frame_index), cls)
            out.append(Detection(b, self._ids[name], name, 0.9, frame_index, timestamp))
        return out

    def info(self) -> dict[str, Any]:
        return {"adapter": "scripted-test", "class_names": {str(k): v for k, v in self.class_names.items()},
                "num_classes": len(self.class_names), "model_file": "synthetic", "device": "cpu"}


def write_video(path: Path, fps: float, n_frames: int, size: tuple[int, int] = (320, 240),
                train: SyntheticTrain | None = None) -> Path:
    """Write an mp4v test video; each frame shows its index as a grey level and optional wagons."""
    w, h = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    assert writer.isOpened(), "OpenCV could not open an mp4v writer for tests"
    try:
        for i in range(n_frames):
            img = np.full((h, w, 3), 30, dtype=np.uint8)
            if train is not None:
                for k in range(len(train.classes)):
                    b = train.box(k, i / fps)
                    if b is not None:
                        cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (60, 120, 200), -1)
            cv2.putText(img, str(i), (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            writer.write(img)
    finally:
        writer.release()
    return path


def make_track(track_id: int, start_sample: int, boxes: list[BBox], class_names: list[str] | str,
               fps: float = 10.0, conf: float = 0.9, edge: bool = False) -> TrackRecord:
    names = [class_names] * len(boxes) if isinstance(class_names, str) else class_names
    rec = TrackRecord(track_id=track_id, state=TrackState.COMPLETED)
    for i, (b, n) in enumerate(zip(boxes, names)):
        s = start_sample + i
        rec.observations.append(TrackObservation(
            track_id=track_id, frame_index=s, sample_index=s, timestamp=s / fps, bbox=b,
            class_id=0, class_name=n, confidence=conf, touches_edge=edge,
        ))
    rec.last_seen_sample = start_sample + len(boxes) - 1
    return rec


def moving_boxes(x0: float, n: int, vx_per_sample: float, y: float = 100.0, w: float = 150.0, h: float = 120.0) -> list[BBox]:
    return [(x0 + i * vx_per_sample, y, x0 + i * vx_per_sample + w, y + h) for i in range(n)]
