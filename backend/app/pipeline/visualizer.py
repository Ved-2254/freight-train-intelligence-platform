"""Annotated video rendering (second pass over the sampled frames, after resolution).

Because rendering happens after the wagon registry has finished, the video shows the *final*
wagon UIDs and sequence positions. Uncertain records are drawn in orange with a '?', records
that were not counted in grey; the ByteTrack ID is shown separately as 'trk N'.
"""

from __future__ import annotations

import colorsys
import zlib
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from app.core.exceptions import OutputWriteError
from app.core.logging import get_logger
from app.pipeline.models import FrameSample, TrackObservation, WagonRecord
from app.pipeline.sequence_builder import UNCERTAIN_FLAGS, MotionSummary

log = get_logger("visualizer")

_UNCERTAIN = (0, 140, 255)  # BGR orange
_NOT_COUNTED = (150, 150, 150)
_LINE = (255, 255, 0)


def class_color(name: str) -> tuple[int, int, int]:
    hue = (zlib.crc32(name.encode()) % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 0.95)
    return int(b * 255), int(g * 255), int(r * 255)


class VideoWriterHandle:
    """cv2.VideoWriter with codec fallback; always call close()."""

    def __init__(self, path: Path, fps: float, size: tuple[int, int], codecs: list[str]):
        self.path = path
        self.codec: str | None = None
        self.frames_written = 0
        self._writer: cv2.VideoWriter | None = None
        path.parent.mkdir(parents=True, exist_ok=True)
        for codec in codecs:
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), fps, size)
            if writer.isOpened():
                self._writer, self.codec = writer, codec
                break
            writer.release()
        if self._writer is None:
            raise OutputWriteError(f"Could not open a video writer for {path.name} with codecs {codecs}")
        log.info("Writing annotated video with codec %s at %.2f fps", self.codec, fps)

    def write(self, frame: np.ndarray) -> None:
        assert self._writer is not None
        self._writer.write(frame)
        self.frames_written += 1

    def close(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None


class FrameAnnotator:
    def __init__(
        self,
        wagons: list[WagonRecord],
        observations: dict[str, list[TrackObservation]],
        motion: MotionSummary | None,
        draw_line: bool,
    ):
        self.by_uid = {w.wagon_uid: w for w in wagons}
        self.by_sample: dict[int, list[tuple[TrackObservation, WagonRecord]]] = defaultdict(list)
        for uid, obs_list in observations.items():
            for o in obs_list:
                self.by_sample[o.sample_index].append((o, self.by_uid[uid]))
        self.motion = motion
        self.draw_line = draw_line
        self.counted_times = sorted(
            (w.reference_time if w.reference_time is not None else w.first_timestamp)
            for w in wagons if w.counted
        )
        self.total_counted = len(self.counted_times)

    def annotate(self, sample: FrameSample) -> np.ndarray:
        img = sample.image
        h, w = img.shape[:2]
        scale = max(0.4, min(1.2, w / 1600))
        thick = max(1, int(round(2 * scale)))

        if self.draw_line and self.motion is not None and self.motion.direction != 0:
            p = int(round(self.motion.reference_position))
            if self.motion.axis == "x":
                cv2.line(img, (p, 0), (p, h), _LINE, thick, cv2.LINE_AA)
            else:
                cv2.line(img, (0, p), (w, p), _LINE, thick, cv2.LINE_AA)

        for obs, wagon in self.by_sample.get(sample.sample_index, []):
            uncertain = bool(wagon.flags & UNCERTAIN_FLAGS)
            if not wagon.counted:
                color = _NOT_COUNTED
            elif uncertain:
                color = _UNCERTAIN
            else:
                color = class_color(wagon.class_name)
            x1, y1, x2, y2 = (int(round(v)) for v in obs.bbox)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, thick if wagon.counted else max(1, thick - 1))
            pos = f"#{wagon.sequence_position} " if wagon.sequence_position else ""
            label = (
                f"{pos}{wagon.wagon_uid} {wagon.class_name}{'?' if uncertain else ''} "
                f"{wagon.class_decision.confidence:.2f} | trk {obs.track_id} ({obs.class_name} {obs.confidence:.2f})"
            )
            if not wagon.counted:
                label += " [not counted]"
            self._label(img, label, x1, y1, color, scale)

        passed = sum(1 for t in self.counted_times if t <= sample.timestamp)
        header = f"t={sample.timestamp:7.2f}s  frame {sample.frame_index}  passed {passed}/{self.total_counted}"
        self._label(img, header, 8, int(30 * scale) + 8, (40, 40, 40), scale * 1.1, text_color=(255, 255, 255))
        return img

    @staticmethod
    def _label(img: np.ndarray, text: str, x: int, y: int, color, scale: float, text_color=(0, 0, 0)) -> None:
        font = cv2.FONT_HERSHEY_SIMPLEX
        fs = 0.55 * scale
        tw, th = cv2.getTextSize(text, font, fs, 1)[0]
        y = max(th + 6, y)
        cv2.rectangle(img, (x, y - th - 6), (x + tw + 6, y), color, -1)
        cv2.putText(img, text, (x + 3, y - 4), font, fs, text_color, 1, cv2.LINE_AA)


def render_video(
    samples: Iterable[FrameSample],
    annotator: FrameAnnotator,
    path: Path,
    fps: float,
    size: tuple[int, int],
    codecs: list[str],
) -> tuple[str, int]:
    """Render annotated frames; returns (codec used, frames written)."""
    writer = VideoWriterHandle(path, fps, size, codecs)
    try:
        for sample in samples:
            frame = annotator.annotate(sample)
            if (frame.shape[1], frame.shape[0]) != size:
                frame = cv2.resize(frame, size)
            writer.write(frame)
    finally:
        writer.close()
    return writer.codec or "", writer.frames_written
