"""ByteTrack adapter.

Wraps Ultralytics' `BYTETracker` so the rest of the pipeline only sees project-owned
`Detection` -> `TrackObservation` conversions. ByteTrack is class-agnostic here: it associates
boxes by motion/IoU; class labels are carried through from the matched detection and
aggregated later. Track IDs are scoped to one tracker instance (one processing run).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Protocol

import numpy as np

from app.core.exceptions import TrackingError
from app.core.logging import get_logger
from app.pipeline.config import TrackConfig, TrackerConfig
from app.pipeline.geometry import touches_edge
from app.pipeline.models import Detection, FrameSample, TrackObservation

log = get_logger("tracker")


class Tracker(Protocol):
    def update(self, detections: list[Detection], sample: FrameSample) -> list[TrackObservation]: ...

    def info(self) -> dict[str, Any]: ...


class _DetectionBatch:
    """Minimal stand-in for Ultralytics `Boxes`, exposing the attributes BYTETracker reads."""

    def __init__(self, detections: list[Detection]):
        if detections:
            xyxy = np.array([d.bbox for d in detections], dtype=np.float32)
            self.conf = np.array([d.confidence for d in detections], dtype=np.float32)
            self.cls = np.array([d.class_id for d in detections], dtype=np.float32)
        else:
            xyxy = np.zeros((0, 4), dtype=np.float32)
            self.conf = np.zeros((0,), dtype=np.float32)
            self.cls = np.zeros((0,), dtype=np.float32)
        self.xyxy = xyxy
        xywh = xyxy.copy()
        xywh[:, 0] = (xyxy[:, 0] + xyxy[:, 2]) / 2
        xywh[:, 1] = (xyxy[:, 1] + xyxy[:, 3]) / 2
        xywh[:, 2] = xyxy[:, 2] - xyxy[:, 0]
        xywh[:, 3] = xyxy[:, 3] - xyxy[:, 1]
        self.xywh = xywh

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, idx: Any) -> "_DetectionBatch":
        sub = _DetectionBatch([])
        sub.xyxy, sub.xywh, sub.conf, sub.cls = self.xyxy[idx], self.xywh[idx], self.conf[idx], self.cls[idx]
        return sub


class ByteTrackAdapter:
    def __init__(self, cfg: TrackerConfig, track_cfg: TrackConfig, frame_rate: float):
        try:
            from ultralytics.trackers.byte_tracker import BYTETracker
        except ImportError as exc:
            raise TrackingError(f"ByteTrack (ultralytics.trackers) is unavailable: {exc}") from exc
        self.cfg = cfg
        self.track_cfg = track_cfg
        self.frame_rate = float(frame_rate)
        # Verified against ultralytics 8.4.174: BYTETracker(args) keeps a lost track for
        # `args.track_buffer` *tracker updates* (sampled frames), independent of frame rate.
        # Convert the configured seconds using the sampling rate so behaviour is cadence-independent.
        self.track_buffer = max(1, int(round(self.frame_rate * cfg.track_buffer_seconds)))
        args = SimpleNamespace(
            tracker_type="bytetrack",
            track_high_thresh=cfg.track_high_thresh,
            track_low_thresh=cfg.track_low_thresh,
            new_track_thresh=cfg.new_track_thresh,
            track_buffer=self.track_buffer,
            match_thresh=cfg.match_thresh,
            fuse_score=cfg.fuse_score,
        )
        # Note: STrack IDs come from a process-global counter that BYTETracker resets on
        # construction, so run one tracking job per process at a time (true for the CLI/worker).
        self._tracker = BYTETracker(args)

    def update(self, detections: list[Detection], sample: FrameSample) -> list[TrackObservation]:
        try:
            rows = self._tracker.update(_DetectionBatch(detections), sample.image)
        except Exception as exc:
            raise TrackingError(f"ByteTrack update failed at frame {sample.frame_index}: {exc}") from exc
        rows = np.asarray(rows)
        if rows.size == 0:
            return []
        out: list[TrackObservation] = []
        h, w = sample.height, sample.width
        for row in rows.reshape(-1, rows.shape[-1]):
            # Row layout (Ultralytics STrack.result): x1, y1, x2, y2, track_id, score, cls, det_idx
            track_id, det_idx = int(row[4]), int(row[7])
            if not 0 <= det_idx < len(detections):
                log.debug("Track %d returned without a valid detection index; skipped", track_id)
                continue
            det = detections[det_idx]
            # Geometry comes from the matched detection, not the Kalman-smoothed track box: the
            # smoothed box lags badly for wagons growing/shrinking at the frame border, which
            # corrupts clipping detection and fragment prediction. ByteTrack supplies identity only.
            out.append(TrackObservation(
                track_id=track_id,
                frame_index=sample.frame_index,
                sample_index=sample.sample_index,
                timestamp=sample.timestamp,
                bbox=det.bbox,
                class_id=det.class_id,
                class_name=det.class_name,
                confidence=det.confidence,
                touches_edge=touches_edge(det.bbox, w, h, self.track_cfg.edge_margin_px),
            ))
        return out

    def info(self) -> dict[str, Any]:
        return {
            "adapter": "ultralytics.BYTETracker",
            "sampling_rate": round(self.frame_rate, 4),
            "track_buffer_frames": self.track_buffer,
            **self.cfg.model_dump(),
        }


def create_tracker(cfg: TrackerConfig, track_cfg: TrackConfig, frame_rate: float) -> ByteTrackAdapter:
    return ByteTrackAdapter(cfg, track_cfg, frame_rate)
