"""Adapter between the job system and the existing pipeline (`app.pipeline.pipeline.process_video`).

* Builds the PipelineConfig from backend/configs/default.yaml plus the job's validated options
  (the model path always comes from the server-side config, never from a client).
* Loads the detector once per worker process and reuses it across jobs.
* Maps pipeline progress events to an honest job progress percentage.
* Maps pipeline exceptions to stable, user-safe error codes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.core.exceptions import (
    ConfigError,
    InferenceError,
    JobCancelledError,
    ModelLoadError,
    OutputWriteError,
    PipelineError,
    TrackingError,
    VideoInputError,
)
from app.core.logging import get_logger
from app.core.settings import ServiceSettings
from app.pipeline.config import PipelineConfig, load_config
from app.pipeline.detector import Detector, create_detector
from app.pipeline.models import ProcessingResult, ProgressEvent
from app.pipeline.pipeline import TrackerFactory, process_video

log = get_logger("worker.runner")

# Client option -> dotted pipeline config key. Only these can be changed per job.
OPTION_TO_CONFIG: dict[str, str] = {
    "target_fps": "sampling.target_fps",
    "confidence_threshold": "detector.confidence_threshold",
    "counting_mode": "counting.mode",
    "line_position": "counting.line_position",
    "travel_axis": "counting.travel_axis",
    "write_video": "output.write_video",
}

# Pipeline exception -> (error code, user-safe message)
_ERRORS: list[tuple[type[BaseException], str, str]] = [
    (VideoInputError, "INVALID_VIDEO", "The video could not be read or decoded during processing"),
    (ModelLoadError, "MODEL_UNAVAILABLE", "The detection model could not be loaded on the server"),
    (InferenceError, "INFERENCE_FAILED", "Object detection failed while processing the video"),
    (TrackingError, "TRACKING_FAILED", "Object tracking failed while processing the video"),
    (OutputWriteError, "OUTPUT_WRITE_FAILED", "The results could not be written on the server"),
    (ConfigError, "INVALID_CONFIGURATION", "The processing configuration is invalid"),
    (PipelineError, "PROCESSING_FAILED", "Processing failed"),
]


def classify_error(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "INSUFFICIENT_STORAGE", "The server ran out of disk space while processing"
    if isinstance(exc, OutputWriteError) and "No space left" in str(exc):
        return "INSUFFICIENT_STORAGE", "The server ran out of disk space while processing"
    for cls, code, message in _ERRORS:
        if isinstance(exc, cls):
            return code, message
    return "INTERNAL_ERROR", "An unexpected error occurred while processing the video"


# Stage -> (start %, end %). Frame-based stages interpolate with real frame counts.
_STAGE_RANGES: dict[str, tuple[float, float]] = {
    "validating": (0.0, 1.0),
    "loading_model": (2.0, 4.0),
    "detecting_and_tracking": (5.0, 85.0),
    "resolving": (86.0, 87.0),
    "rendering": (88.0, 99.0),
    "completed": (99.0, 99.0),  # 100 is set when results are recorded
}

STAGE_MESSAGES = {
    "validating": "Validating the video",
    "loading_model": "Loading the detection model",
    "detecting_and_tracking": "Detecting and tracking wagons",
    "resolving": "Resolving wagon identities, counting and sequencing",
    "rendering": "Rendering the annotated video",
    "completed": "Saving results",
}


class ProgressMapper:
    """Turns pipeline events into a monotonic job percentage (None when not computable)."""

    def __init__(self) -> None:
        self.last = 0.0

    def map(self, event: ProgressEvent) -> tuple[str, float | None, str]:
        lo, hi = _STAGE_RANGES.get(event.stage, (self.last, self.last))
        if hi > lo:
            if event.total_frames:
                frac = min(1.0, max(0.0, event.frames_processed / event.total_frames))
                pct: float | None = lo + (hi - lo) * frac
            elif event.stage in ("detecting_and_tracking", "rendering"):
                pct = None  # unknown total: report the stage only
            else:
                pct = lo
        else:
            pct = lo
        if pct is not None:
            pct = max(self.last, round(pct, 1))
            self.last = pct
        message = STAGE_MESSAGES.get(event.stage, event.message)
        if event.stage in ("detecting_and_tracking", "rendering") and event.frames_processed:
            total = f"/{event.total_frames}" if event.total_frames else ""
            message = f"{message} (frame {event.frames_processed}{total})"
        return event.stage, pct, message


DetectorFactory = Callable[[PipelineConfig], Detector]


@dataclass
class RunContext:
    job_id: str
    input_path: Path
    output_dir: Path
    options: dict[str, Any]
    on_progress: Callable[[str, float | None, str], None]
    should_cancel: Callable[[], bool]


class PipelineRunner:
    def __init__(
        self,
        settings: ServiceSettings,
        detector_factory: DetectorFactory | None = None,
        tracker_factory: TrackerFactory | None = None,
    ):
        self.settings = settings
        self._detector_factory = detector_factory
        self._tracker_factory = tracker_factory
        self._detector: Detector | None = None
        self._detector_key: str | None = None

    def build_config(self, options: dict[str, Any]) -> PipelineConfig:
        unknown = set(options) - set(OPTION_TO_CONFIG)
        if unknown:
            raise ConfigError(f"Unsupported job options: {sorted(unknown)}")
        overrides = {OPTION_TO_CONFIG[k]: v for k, v in options.items()}
        return load_config(self.settings.pipeline_config, overrides)

    def detector_for(self, config: PipelineConfig) -> Detector:
        """Reuse the loaded model while detector settings are unchanged (model loads once)."""
        key = json.dumps([str(config.resolved_model_path()), config.detector.model_dump(mode="json")], sort_keys=True)
        if self._detector is None or key != self._detector_key:
            factory = self._detector_factory or (lambda cfg: create_detector(cfg.detector, cfg.resolved_model_path()))
            self._detector = factory(config)
            self._detector_key = key
        return self._detector

    def run(self, ctx: RunContext) -> tuple[ProcessingResult, PipelineConfig]:
        config = self.build_config(ctx.options)
        mapper = ProgressMapper()  # all progress goes through one mapper so it never moves backwards
        ctx.on_progress(*mapper.map(ProgressEvent("loading_model", STAGE_MESSAGES["loading_model"])))
        detector = self.detector_for(config)

        def progress(event: ProgressEvent) -> None:
            ctx.on_progress(*mapper.map(event))

        result = process_video(
            ctx.input_path,
            config,
            run_dir=ctx.output_dir,
            run_id=ctx.job_id,
            progress=progress,
            detector=detector,
            tracker_factory=self._tracker_factory,
            should_cancel=ctx.should_cancel,
        )
        return result, config


__all__ = ["PipelineRunner", "RunContext", "ProgressMapper", "classify_error", "JobCancelledError", "OPTION_TO_CONFIG"]
