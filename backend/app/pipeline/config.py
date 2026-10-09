"""Validated pipeline configuration.

All tunable values live here (and in `backend/configs/default.yaml`), not as literals in the
algorithm modules. Relative paths inside a config file resolve against the project root;
paths given on the command line resolve against the current working directory (the CLI
makes them absolute before building the config).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.exceptions import ConfigError

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_CONFIG_PATH = BACKEND_DIR / "configs" / "default.yaml"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DetectorConfig(_Section):
    model_path: str = "backend/models/best.pt"
    confidence_threshold: float = Field(0.10, ge=0.0, le=1.0)
    iou_threshold: float = Field(0.50, gt=0.0, le=1.0)
    image_size: int = Field(640, ge=32)
    device: str = "auto"  # "auto", "cpu", "cuda", "cuda:0", "0", ...
    half: bool = False
    agnostic_nms: bool = True
    max_det: int = Field(100, ge=1)
    # Boxes with a side shorter than this (e.g. slivers at the frame border) are discarded.
    min_box_size_px: int = Field(12, ge=1)
    # Optional guard: fail fast if the loaded model's class names differ from this list.
    expected_classes: list[str] | None = None


class SamplingConfig(_Section):
    # Analysis cadence in frames per second. Sources at or below this rate are processed
    # frame-by-frame (never upsampled); faster sources are subsampled by timestamp.
    target_fps: float = Field(30.0, gt=0.0)
    max_frames: int | None = Field(None, ge=1)  # cap on *sampled* frames, for quick tests


class TrackerConfig(_Section):
    # ByteTrack association parameters (Ultralytics BYTETracker semantics).
    track_high_thresh: float = Field(0.25, ge=0.0, le=1.0)
    track_low_thresh: float = Field(0.10, ge=0.0, le=1.0)
    new_track_thresh: float = Field(0.25, ge=0.0, le=1.0)
    match_thresh: float = Field(0.80, gt=0.0, le=1.0)
    fuse_score: bool = True
    # How long a lost track can be recovered by ByteTrack, in seconds (converted to frames
    # using the effective sampling rate so behaviour does not change with target_fps).
    track_buffer_seconds: float = Field(1.0, gt=0.0)


class TrackConfig(_Section):
    min_hits: int = Field(3, ge=1)  # observations before a track is "confirmed"
    edge_margin_px: int = Field(4, ge=0)  # box within this distance of the border = truncated
    edge_observation_weight: float = Field(0.5, ge=0.0, le=1.0)  # class-vote weight of truncated boxes


class ClassConfig(_Section):
    min_class_share: float = Field(0.60, gt=0.0, le=1.0)  # winning share of weighted votes
    min_class_observations: int = Field(3, ge=1)  # supporting observations for the winner
    unresolved_label: str = "Unresolved"


class ResolutionConfig(_Section):
    # Fragment linking (track A ends, track B starts later, same physical wagon?)
    max_gap_seconds: float = Field(1.5, ge=0.0)
    max_center_distance_ratio: float = Field(0.5, gt=0.0)  # x box width of track A
    max_size_ratio: float = Field(1.5, ge=1.0)  # allowed width/height change factor
    motion_fit_window: int = Field(15, ge=2)  # last N observations used for velocity
    min_speed_px_per_s: float = Field(5.0, ge=0.0)  # below this a track counts as stationary
    # Concurrent duplicate tracks on the same wagon
    duplicate_iou: float = Field(0.60, gt=0.0, le=1.0)
    duplicate_containment: float = Field(0.85, gt=0.0, le=1.0)
    duplicate_overlap_fraction: float = Field(0.80, gt=0.0, le=1.0)
    duplicate_candidate_iou: float = Field(0.30, gt=0.0, le=1.0)
    # Minimum evidence for a wagon record to be counted
    min_observations: int = Field(5, ge=1)
    min_duration_seconds: float = Field(0.20, ge=0.0)
    # Sudden centre jumps larger than this x box width are flagged as possible ID switches
    id_switch_jump_ratio: float = Field(0.6, gt=0.0)
    id_switch_min_px: float = Field(20.0, ge=0.0)  # floor for the jump threshold (tiny boxes)


class CountingConfig(_Section):
    mode: Literal["registry", "line"] = "registry"
    # Reference line used for line counting AND for sequence ordering, as a fraction of the
    # frame size along the travel axis (0.5 = centre of the frame).
    line_position: float = Field(0.5, ge=0.0, le=1.0)
    travel_axis: Literal["auto", "x", "y"] = "auto"
    expected_direction: Literal["auto", "positive", "negative"] = "auto"
    hysteresis_px: float = Field(5.0, ge=0.0)
    # Classes that are detected, tracked and listed in the sequence but NOT counted as wagons in
    # the headline total (`wagons_only_total`). Project default: locomotives are not wagons.
    exclude_from_wagon_total: list[str] = Field(default_factory=lambda: ["Locomotive"])
    # Sampled frames at the start/end of the video in which a visible record is
    # considered potentially cut off by the recording.
    boundary_seconds: float = Field(0.5, ge=0.0)
    # Objects that do not move with the passing train (e.g. rolling stock parked on another
    # track) are reported but not counted. Applied only while other wagons visible at the same
    # time are clearly moving; a record is stationary when BOTH its speed is below
    # `stationary_speed_ratio` x the median speed of those wagons AND it travels less than
    # `stationary_max_travel_ratio` x its own box length along the travel axis.
    exclude_stationary: bool = True
    stationary_speed_ratio: float = Field(0.5, gt=0.0, le=1.0)
    stationary_max_travel_ratio: float = Field(0.5, gt=0.0)
    # Only wagons moving with the train at >= this fraction of its median speed serve as the
    # moving reference (perspective views make near/far wagons appear at different speeds).
    stationary_reference_ratio: float = Field(0.25, gt=0.0, le=1.0)


class OutputConfig(_Section):
    output_dir: str = "data/outputs"
    write_video: bool = True
    video_codecs: list[str] = Field(default_factory=lambda: ["avc1", "mp4v"])
    save_tracks_csv: bool = True
    draw_counting_line: bool = True


class PipelineConfig(_Section):
    detector: DetectorConfig = Field(default_factory=DetectorConfig)
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)
    tracker: TrackerConfig = Field(default_factory=TrackerConfig)
    track: TrackConfig = Field(default_factory=TrackConfig)
    classes: ClassConfig = Field(default_factory=ClassConfig)
    resolution: ResolutionConfig = Field(default_factory=ResolutionConfig)
    counting: CountingConfig = Field(default_factory=CountingConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def _check_thresholds(self) -> "PipelineConfig":
        if self.tracker.track_low_thresh > self.tracker.track_high_thresh:
            raise ValueError("tracker.track_low_thresh must be <= tracker.track_high_thresh")
        return self

    def resolved_model_path(self) -> Path:
        return resolve_path(self.detector.model_path)

    def resolved_output_dir(self) -> Path:
        return resolve_path(self.output.output_dir)


def resolve_path(value: str | Path) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


def _set_dotted(data: dict[str, Any], dotted: str, value: Any) -> None:
    node = data
    *parents, leaf = dotted.split(".")
    for key in parents:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            raise ConfigError(f"Cannot set '{dotted}': '{key}' is not a section")
    node[leaf] = value


def load_config(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> PipelineConfig:
    """Load YAML (default: backend/configs/default.yaml if present) and apply dotted overrides.

    `overrides` maps e.g. "detector.model_path" -> value; `None` values are ignored.
    """
    data: dict[str, Any] = {}
    cfg_path = Path(path) if path else (DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else None)
    if cfg_path is not None:
        if not cfg_path.is_file():
            raise ConfigError(f"Config file not found: {cfg_path}")
        try:
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {cfg_path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError(f"Config root must be a mapping: {cfg_path}")
        data = loaded
    for key, value in (overrides or {}).items():
        if value is not None:
            _set_dotted(data, key, value)
    try:
        return PipelineConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration:\n{exc}") from exc
