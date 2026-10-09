"""Per-track observation histories and a project-owned track state machine.

ByteTrack only reports tracks that were matched in the current frame; the states here
(tentative / confirmed / temporarily_lost / completed) are derived by this module and do not
depend on tracker internals.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.pipeline.class_aggregation import aggregate_class
from app.pipeline.config import ClassConfig, TrackConfig
from app.pipeline.models import ClassDecision, FrameSample, TrackObservation, TrackRecord, TrackState

log = get_logger("tracks")


class TrackManager:
    def __init__(self, track_cfg: TrackConfig, class_cfg: ClassConfig, lost_timeout_seconds: float):
        self.cfg = track_cfg
        self.class_cfg = class_cfg
        self.lost_timeout = lost_timeout_seconds
        self.tracks: dict[int, TrackRecord] = {}
        self._last_ts: float = 0.0

    def update(self, observations: list[TrackObservation], sample: FrameSample) -> None:
        seen: set[int] = set()
        for obs in observations:
            if obs.track_id in seen:
                log.debug("Tracker reported track %d twice in frame %d; keeping first", obs.track_id, obs.frame_index)
                continue
            seen.add(obs.track_id)
            rec = self.tracks.get(obs.track_id)
            if rec is None:
                rec = self.tracks[obs.track_id] = TrackRecord(track_id=obs.track_id)
            rec.observations.append(obs)
            rec.last_seen_sample = sample.sample_index
            rec.state = TrackState.CONFIRMED if rec.n >= self.cfg.min_hits else TrackState.TENTATIVE

        for rec in self.tracks.values():
            if rec.track_id in seen or rec.state == TrackState.COMPLETED:
                continue
            if sample.timestamp - rec.last.timestamp > self.lost_timeout:
                rec.state = TrackState.COMPLETED
            else:
                rec.state = TrackState.LOST
        self._last_ts = sample.timestamp

    def finalize(self) -> list[TrackRecord]:
        for rec in self.tracks.values():
            rec.state = TrackState.COMPLETED
        return self.records()

    def records(self) -> list[TrackRecord]:
        return sorted((r for r in self.tracks.values() if r.observations), key=lambda r: (r.first.timestamp, r.track_id))

    def active_count(self) -> int:
        return sum(1 for r in self.tracks.values() if r.state in (TrackState.CONFIRMED, TrackState.TENTATIVE))

    def class_decision(self, rec: TrackRecord) -> ClassDecision:
        return aggregate_class(rec.observations, self.class_cfg, self.cfg.edge_observation_weight)
