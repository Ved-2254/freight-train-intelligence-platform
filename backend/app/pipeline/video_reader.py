"""Video validation, metadata extraction and timestamp-based frame sampling.

`target_fps` is the *analysis cadence*: a 60 fps source sampled at 30 keeps roughly every
second frame; a 25 fps source is processed frame-by-frame (never upsampled by duplication).
Original frame indices and real timestamps are preserved on every sample.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import cv2

from app.core.exceptions import VideoInputError
from app.core.logging import get_logger
from app.pipeline.models import FrameSample, VideoMetadata

log = get_logger("video")

_FALLBACK_FPS = 30.0


def _fourcc_to_str(value: float) -> str | None:
    code = int(value)
    if code <= 0:
        return None
    chars = "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4))
    return chars if chars.isprintable() and chars.strip() else None


def _valid_number(value: float) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def inspect_video(path: str | Path) -> VideoMetadata:
    """Validate that the file exists and decodes; return container metadata."""
    p = Path(path)
    if not p.exists():
        raise VideoInputError(f"Input video not found: {p}")
    if not p.is_file():
        raise VideoInputError(f"Input path is not a file: {p}")
    size = p.stat().st_size
    if size == 0:
        raise VideoInputError(f"Input video is empty (0 bytes): {p}")

    cap = cv2.VideoCapture(str(p))
    try:
        if not cap.isOpened():
            raise VideoInputError(f"OpenCV could not open the video (unsupported or corrupt): {p.name}")
        ok, frame = cap.read()
        if not ok or frame is None:
            raise VideoInputError(f"Video opened but no frame could be decoded: {p.name}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or frame.shape[1]
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or frame.shape[0]
        codec = _fourcc_to_str(cap.get(cv2.CAP_PROP_FOURCC))
    finally:
        cap.release()

    fps_v = float(fps) if _valid_number(fps) and fps < 1000 else None
    count_v = int(count) if _valid_number(count) else None
    duration = count_v / fps_v if fps_v and count_v else None
    if fps_v is None:
        log.warning("Video reports no valid FPS; timestamps will rely on decoder positions")
    return VideoMetadata(
        path=str(p),
        width=int(width),
        height=int(height),
        fps=fps_v,
        frame_count=count_v,
        duration_seconds=duration,
        codec=codec,
        file_size_bytes=size,
    )


@dataclass
class SamplingStats:
    """Filled in while iterating; describes what the sampler actually did."""

    source_fps: float | None = None
    target_fps: float = 0.0
    decoded_frames: int = 0
    sampled_frames: int = 0
    timestamp_source: str = "decoder"  # "decoder" | "frame_index" | "mixed"
    timestamp_fallbacks: int = 0
    first_timestamp: float = 0.0
    last_timestamp: float = 0.0
    stopped_early: bool = False

    @property
    def effective_fps(self) -> float:
        """Average sampled-frame rate actually achieved (planned rate until 2+ samples exist)."""
        span = self.last_timestamp - self.first_timestamp
        if self.sampled_frames > 1 and span > 0:
            return (self.sampled_frames - 1) / span
        return planned_sampling_rate(self.source_fps, self.target_fps)

    def to_dict(self) -> dict:
        return {
            "source_fps": self.source_fps,
            "target_fps": self.target_fps,
            "effective_fps": round(self.effective_fps, 4),
            "decoded_frames": self.decoded_frames,
            "sampled_frames": self.sampled_frames,
            "timestamp_source": self.timestamp_source,
            "timestamp_fallbacks": self.timestamp_fallbacks,
            "stopped_early": self.stopped_early,
            "target_fps_meaning": "analysis sampling cadence; output video plays sampled frames at the effective rate",
        }


def planned_sampling_rate(source_fps: float | None, target_fps: float) -> float:
    """Rate the sampler will aim for: never above the source rate."""
    return min(target_fps, source_fps) if source_fps else target_fps


def iter_samples(
    path: str | Path,
    target_fps: float,
    source_fps: float | None = None,
    max_frames: int | None = None,
    stats: SamplingStats | None = None,
) -> Iterator[FrameSample]:
    """Yield sampled frames in temporal order. Releases the capture on exit or error.

    Timestamps come from the decoder (CAP_PROP_POS_MSEC) when it is valid and increasing,
    otherwise from frame_index / fps.
    """
    stats = stats if stats is not None else SamplingStats()
    stats.source_fps = source_fps
    stats.target_fps = target_fps
    fps_for_index = source_fps or _FALLBACK_FPS
    keep_all = source_fps is not None and source_fps <= target_fps * 1.0001
    interval = 1.0 / target_fps
    # Tolerance of half a source frame so sampling does not drift on rate ratios like 50->30.
    tolerance = 0.5 / fps_for_index

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise VideoInputError(f"OpenCV could not open the video: {Path(path).name}")
    used_decoder = used_index = False
    try:
        frame_index = -1
        next_t = 0.0
        prev_ts = -1.0
        while True:
            if not cap.grab():
                break
            frame_index += 1
            stats.decoded_frames += 1

            pos_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            ts = pos_ms / 1000.0 if pos_ms is not None and math.isfinite(pos_ms) else -1.0
            if ts < 0 or (frame_index > 0 and ts <= prev_ts):
                ts = frame_index / fps_for_index
                if ts <= prev_ts:  # keep strictly increasing even if decoder times were ahead
                    ts = prev_ts + 1.0 / fps_for_index
                stats.timestamp_fallbacks += 1
                used_index = True
            else:
                used_decoder = True
            prev_ts = ts

            if not keep_all and ts + tolerance < next_t:
                continue
            ok, image = cap.retrieve()
            if not ok or image is None:
                log.warning("Frame %d could not be decoded; skipping", frame_index)
                continue
            if not keep_all:
                while next_t <= ts + tolerance:
                    next_t += interval
            if stats.sampled_frames == 0:
                stats.first_timestamp = ts
            sample = FrameSample(image=image, frame_index=frame_index, timestamp=ts, sample_index=stats.sampled_frames)
            stats.sampled_frames += 1
            stats.last_timestamp = ts
            yield sample
            if max_frames is not None and stats.sampled_frames >= max_frames:
                stats.stopped_early = True
                break
    finally:
        cap.release()
        stats.timestamp_source = "mixed" if used_decoder and used_index else ("frame_index" if used_index else "decoder")
