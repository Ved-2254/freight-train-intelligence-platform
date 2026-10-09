"""Project-owned domain models (internal contracts between pipeline stages).

Identifier vocabulary:
  * run_id     - one processing attempt (becomes job_id once a job system exists)
  * track_id   - ByteTrack-assigned identity, scoped to one run, never a wagon identity
  * wagon_uid  - resolved physical-wagon record within one result ("W001", ...)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable

import numpy as np

BBox = tuple[float, float, float, float]  # x1, y1, x2, y2 in source-frame pixels


@dataclass(frozen=True)
class VideoMetadata:
    path: str
    width: int
    height: int
    fps: float | None
    frame_count: int | None  # as reported by the container (may be inaccurate)
    duration_seconds: float | None
    codec: str | None
    file_size_bytes: int


@dataclass
class FrameSample:
    image: np.ndarray
    frame_index: int  # original decoded frame index (0-based)
    timestamp: float  # seconds
    sample_index: int  # 0-based index among sampled frames

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    @property
    def width(self) -> int:
        return int(self.image.shape[1])


@dataclass(frozen=True)
class Detection:
    bbox: BBox
    class_id: int
    class_name: str
    confidence: float
    frame_index: int
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrackObservation:
    track_id: int
    frame_index: int
    sample_index: int
    timestamp: float
    bbox: BBox  # tracker-smoothed box
    class_id: int
    class_name: str
    confidence: float  # detection confidence of the associated detection
    touches_edge: bool = False

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


class TrackState(str, Enum):
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    LOST = "temporarily_lost"
    COMPLETED = "completed"


@dataclass
class ClassDecision:
    class_name: str  # final class or the configured unresolved label
    confidence: float  # winning share of weighted votes (0..1)
    mean_detection_confidence: float  # mean detector confidence of winning-class observations
    supporting_observations: int
    uncertain: bool
    distribution: dict[str, float]  # class -> normalised weighted vote share
    best_guess: str | None = None  # top-voted class even when uncertain
    runner_up: str | None = None


@dataclass
class TrackRecord:
    track_id: int
    observations: list[TrackObservation] = field(default_factory=list)
    state: TrackState = TrackState.TENTATIVE
    last_seen_sample: int = -1

    @property
    def first(self) -> TrackObservation:
        return self.observations[0]

    @property
    def last(self) -> TrackObservation:
        return self.observations[-1]

    @property
    def n(self) -> int:
        return len(self.observations)

    @property
    def duration(self) -> float:
        return self.last.timestamp - self.first.timestamp if self.observations else 0.0


class CountStatus(str, Enum):
    COUNTED = "counted"
    NOT_COUNTED_INSUFFICIENT_EVIDENCE = "not_counted_insufficient_evidence"
    NOT_COUNTED_NO_LINE_CROSSING = "not_counted_no_line_crossing"


class WagonFlag(str, Enum):
    CLASS_UNCERTAIN = "class_uncertain"
    FRAGMENT_MERGED = "fragment_merged"
    DUPLICATE_MERGED = "duplicate_merged"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    POSSIBLE_ID_SWITCH = "possible_id_switch"
    PARTIAL_AT_START = "partial_at_start"
    PARTIAL_AT_END = "partial_at_end"
    SEQUENCE_EXTRAPOLATED = "sequence_extrapolated"
    DIRECTION_INCONSISTENT = "direction_inconsistent"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass
class WagonRecord:
    wagon_uid: str
    track_ids: list[int]
    class_decision: ClassDecision
    first_timestamp: float
    last_timestamp: float
    first_frame: int
    last_frame: int
    n_observations: int
    count_status: CountStatus = CountStatus.COUNTED
    flags: set[WagonFlag] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)
    # Ordering information
    reference_time: float | None = None  # when the centre passed the reference line
    crossing_time: float | None = None  # validated crossing (line mode) if any
    crossing_direction: int | None = None  # +1 / -1 along the travel axis
    mean_velocity: float | None = None  # px/s along the travel axis
    sequence_position: int | None = None

    @property
    def class_name(self) -> str:
        return self.class_decision.class_name

    @property
    def counted(self) -> bool:
        return self.count_status == CountStatus.COUNTED


@dataclass
class SequenceItem:
    position: int
    wagon_uid: str
    class_name: str
    class_confidence: float
    reference_time: float | None
    crossing_time: float | None
    first_seen: float
    uncertain: bool
    flags: list[str]


@dataclass
class CountResult:
    mode: str
    total_counted: int
    wagons_only_total: int
    excluded_classes: list[str]
    type_counts: dict[str, int]
    not_counted: int
    tracker_ids_seen: int


@dataclass
class ProgressEvent:
    stage: str
    message: str
    frames_processed: int = 0
    total_frames: int | None = None

    @property
    def percent(self) -> float | None:
        if self.total_frames:
            return min(100.0, 100.0 * self.frames_processed / self.total_frames)
        return None


ProgressCallback = Callable[[ProgressEvent], None]


@dataclass
class ProcessingResult:
    run_id: str
    status: str  # "completed" | "failed"
    video: VideoMetadata | None
    model: dict[str, Any]
    config: dict[str, Any]
    sampling: dict[str, Any]
    timing: dict[str, float]
    counts: CountResult | None
    sequence: list[SequenceItem]
    sequence_info: dict[str, Any]
    wagons: list[WagonRecord]
    warnings: list[str]
    unresolved_identities: list[dict[str, Any]]
    artifacts: dict[str, str]  # name -> path relative to the run output directory
    output_dir: str
    error: str | None = None
