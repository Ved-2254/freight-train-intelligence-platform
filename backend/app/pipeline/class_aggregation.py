"""Class stabilisation across a track's observations.

The detector exposes only the top-1 class and its confidence per box, so this is a
confidence-weighted vote over top-1 predictions:

    S(c) = sum_i  w_i * conf_i * [class_i == c]

with w_i = 1.0 for fully visible boxes and `edge_observation_weight` for boxes touching the
frame border (likely truncated). Scores are NOT calibrated probabilities; the reported class
confidence is the winner's share of the total weighted vote.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.pipeline.config import ClassConfig
from app.pipeline.models import ClassDecision, TrackObservation


def aggregate_class(
    observations: Iterable[TrackObservation],
    cfg: ClassConfig,
    edge_weight: float,
) -> ClassDecision:
    scores: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    conf_sum: dict[str, float] = defaultdict(float)
    for obs in observations:
        w = edge_weight if obs.touches_edge else 1.0
        scores[obs.class_name] += w * obs.confidence
        counts[obs.class_name] += 1
        conf_sum[obs.class_name] += obs.confidence

    total = sum(scores.values())
    if not counts:
        return ClassDecision(cfg.unresolved_label, 0.0, 0.0, 0, True, {})
    if total <= 0:  # every observation had zero weight/confidence: fall back to raw counts
        scores = {k: float(v) for k, v in counts.items()}
        total = float(sum(counts.values()))

    # Deterministic ordering: score desc, then observation count desc, then name.
    ranked = sorted(scores, key=lambda c: (-scores[c], -counts[c], c))
    winner = ranked[0]
    share = scores[winner] / total
    runner_up = ranked[1] if len(ranked) > 1 else None
    tie = runner_up is not None and abs(scores[runner_up] - scores[winner]) <= 1e-9
    uncertain = tie or share < cfg.min_class_share or counts[winner] < cfg.min_class_observations
    distribution = {c: round(scores[c] / total, 4) for c in ranked}
    return ClassDecision(
        class_name=cfg.unresolved_label if uncertain else winner,
        confidence=round(share, 4),
        mean_detection_confidence=round(conf_sum[winner] / counts[winner], 4),
        supporting_observations=counts[winner],
        uncertain=uncertain,
        distribution=distribution,
        best_guess=winner,
        runner_up=runner_up,
    )
