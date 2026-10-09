"""Resolve ByteTrack tracks into physical-wagon records.

Resolution runs once, after tracking, over the complete track histories, so it is
deterministic and auditable. Three steps:

1. Split at identity switches - a track whose box jumps further than its own motion predicts
   (typically a tracker ID hopping from one wagon to the next, e.g. on slivers at the frame
   border) is cut into segments. Segments are flagged `possible_id_switch`.
2. Concurrent duplicates - two segments that coexist and overlap (high IoU / containment) in
   most of their shared frames are treated as the same wagon. Weaker overlap is only flagged.
3. Sequential fragments - segment A ends, segment B starts within `max_gap_seconds`, and B starts
   where A's motion predicts (measured on unclipped box edges), with compatible size and
   direction. A link is made only when it is the *unique* viable option for both A and B;
   otherwise every involved record is flagged `ambiguous_identity` and kept separate (possible
   over-count, never a silent merge).

Matching class labels are never a reason to merge; confidently different classes block a merge.
Segments that coexist without duplicate-level overlap are never merged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.pipeline import geometry, motion
from app.pipeline.class_aggregation import aggregate_class
from app.pipeline.config import ClassConfig, CountingConfig, ResolutionConfig, TrackConfig
from app.pipeline.models import (
    ClassDecision,
    CountStatus,
    TrackObservation,
    TrackRecord,
    WagonFlag,
    WagonRecord,
)

log = get_logger("registry")


@dataclass
class _Group:
    """Observations believed to belong to one wagon (one or more track segments)."""

    key: int  # unique segment key, used by cannot-link constraints
    track_ids: list[int]
    observations: list[TrackObservation]
    flags: set[WagonFlag] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)
    member_keys: set[int] = field(default_factory=set)  # keys of all groups merged into this one

    @property
    def first(self) -> TrackObservation:
        return self.observations[0]

    @property
    def last(self) -> TrackObservation:
        return self.observations[-1]


@dataclass
class RegistryResult:
    wagons: list[WagonRecord]
    observations: dict[str, list[TrackObservation]]  # wagon_uid -> observations (time order)
    track_to_wagons: dict[int, list[str]]  # a split tracker ID can map to several wagons
    unresolved: list[dict[str, Any]]
    warnings: list[str]


def _dedupe(observations: list[TrackObservation]) -> list[TrackObservation]:
    """One observation per sample: keep the highest-confidence one (ties -> lowest track id)."""
    best: dict[int, TrackObservation] = {}
    for o in observations:
        cur = best.get(o.sample_index)
        if cur is None or (o.confidence, -o.track_id) > (cur.confidence, -cur.track_id):
            best[o.sample_index] = o
    return [best[k] for k in sorted(best)]


class WagonRegistry:
    def __init__(
        self,
        resolution: ResolutionConfig,
        track_cfg: TrackConfig,
        class_cfg: ClassConfig,
        counting: CountingConfig,
    ):
        self.cfg = resolution
        self.track_cfg = track_cfg
        self.class_cfg = class_cfg
        self.counting = counting
        self.frame_size: motion.FrameSize = None

    @property
    def _margin(self) -> float:
        return self.track_cfg.edge_margin_px

    # ------------------------------------------------------------------ public
    def resolve(self, tracks: list[TrackRecord], frame_size: motion.FrameSize = None) -> RegistryResult:
        """Resolve completed tracks. `frame_size` (w, h) enables clipping-aware motion; None = unknown."""
        self.frame_size = frame_size
        tracks = [t for t in sorted(tracks, key=lambda r: (r.first.timestamp, r.track_id)) if t.observations]
        unresolved: list[dict[str, Any]] = []
        warnings: list[str] = []

        segments = self._split_tracks(tracks)
        groups, cannot_link = self._merge_duplicates(segments, unresolved)
        groups = self._link_fragments(groups, cannot_link, unresolved)

        wagons: list[WagonRecord] = []
        obs_map: dict[str, list[TrackObservation]] = {}
        track_to_wagons: dict[int, list[str]] = {}
        groups.sort(key=lambda g: (g.first.timestamp, min(g.track_ids), g.key))
        for i, g in enumerate(groups, start=1):
            uid = f"W{i:03d}"
            decision = aggregate_class(g.observations, self.class_cfg, self.track_cfg.edge_observation_weight)
            wagons.append(self._build_record(uid, g, decision))
            obs_map[uid] = g.observations
            for tid in sorted({o.track_id for o in g.observations} | set(g.track_ids)):
                track_to_wagons.setdefault(tid, []).append(uid)

        for item in unresolved:
            keys = set(item.pop("_keys", []))
            item["wagon_uids"] = sorted(
                wagons[i].wagon_uid for i, g in enumerate(groups) if keys & (g.member_keys or {g.key})
            )

        split = sum(1 for uids in track_to_wagons.values() if len(uids) > 1)
        merged = sum(1 for w in wagons if len(w.track_ids) > 1)
        log.info(
            "Registry: %d tracks -> %d wagon records (%d multi-track, %d tracks split), %d unresolved cases",
            len(tracks), len(wagons), merged, split, len(unresolved),
        )
        if unresolved:
            warnings.append(f"{len(unresolved)} identity case(s) could not be resolved confidently; see unresolved_identities")
        if split:
            warnings.append(f"{split} tracker ID(s) were split at suspected identity switches")
        return RegistryResult(wagons, obs_map, track_to_wagons, unresolved, warnings)

    # --------------------------------------------------------------- split
    def _jump_threshold(self, p: TrackObservation, q: TrackObservation) -> float:
        return max(self.cfg.id_switch_jump_ratio * max(p.width, q.width, p.height, q.height), self.cfg.id_switch_min_px)

    def _step_residual(self, p: TrackObservation, q: TrackObservation, v: tuple[float, float]) -> float | None:
        """Distance between q and p moved by velocity v, on comparable (unclipped) edges."""
        dt = q.timestamp - p.timestamp
        err_sq, comparable = 0.0, False
        for axis, va in zip(motion.AXES, v):
            pair = motion.common_anchor(p, q, axis, self.frame_size, self._margin)
            if pair is not None:
                comparable = True
                err_sq += (pair[1] - (pair[0] + va * dt)) ** 2
        return err_sq ** 0.5 if comparable else None

    def _split_tracks(self, tracks: list[TrackRecord]) -> list[_Group]:
        segments: list[_Group] = []
        for t in tracks:
            obs = t.observations
            v = motion.velocity(obs, self.frame_size, self._margin)
            cuts = [0]
            for i, (p, q) in enumerate(zip(obs, obs[1:]), start=1):
                r = self._step_residual(p, q, v)
                if r is not None and r > self._jump_threshold(p, q):
                    cuts.append(i)
            cuts.append(len(obs))
            pieces = [obs[a:b] for a, b in zip(cuts, cuts[1:])]
            for piece in pieces:
                g = _Group(key=len(segments), track_ids=[t.track_id], observations=list(piece))
                if len(pieces) > 1:
                    g.flags.add(WagonFlag.POSSIBLE_ID_SWITCH)
                    g.notes.append(
                        f"tracker ID {t.track_id} split at suspected identity switch(es) "
                        f"t={[round(obs[c].timestamp, 3) for c in cuts[1:-1]]}"
                    )
                segments.append(g)
        return segments

    # --------------------------------------------------------- duplicates
    def _merge_duplicates(
        self, segments: list[_Group], unresolved: list[dict[str, Any]]
    ) -> tuple[list[_Group], set[frozenset[int]]]:
        """Union concurrent duplicate segments; return groups and key pairs that must never be linked."""
        cfg = self.cfg
        parent = {s.key: s.key for s in segments}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        ordered = sorted(segments, key=lambda s: (s.first.timestamp, s.key))
        by_sample = {s.key: {o.sample_index: o for o in s.observations} for s in segments}
        cannot_link: set[frozenset[int]] = set()
        duplicate_pairs: list[tuple[int, int]] = []
        candidate_pairs: list[tuple[int, int, float]] = []

        for i, a in enumerate(ordered):
            sa = by_sample[a.key]
            for b in ordered[i + 1:]:
                if b.first.timestamp > a.last.timestamp:
                    break  # sorted by start time: no later segment can overlap a
                sb = by_sample[b.key]
                common = sa.keys() & sb.keys()
                if not common:
                    continue
                ious = [geometry.iou(sa[k].bbox, sb[k].bbox) for k in common]
                conts = [geometry.containment(sa[k].bbox, sb[k].bbox) for k in common]
                strong = sum(1 for u, c in zip(ious, conts) if u >= cfg.duplicate_iou or c >= cfg.duplicate_containment)
                shorter = min(len(sa), len(sb))
                mean_iou = sum(ious) / len(ious)
                if (
                    strong >= cfg.duplicate_overlap_fraction * len(common)
                    and len(common) >= cfg.duplicate_overlap_fraction * shorter
                ):
                    duplicate_pairs.append((a.key, b.key))
                else:
                    cannot_link.add(frozenset((a.key, b.key)))
                    if mean_iou >= cfg.duplicate_candidate_iou:
                        candidate_pairs.append((a.key, b.key, mean_iou))

        members: dict[int, set[int]] = {s.key: {s.key} for s in segments}
        rejected: list[tuple[int, int]] = []
        for x, y in duplicate_pairs:
            rx, ry = find(x), find(y)
            if rx == ry:
                continue
            if any(frozenset((p, q)) in cannot_link for p in members[rx] for q in members[ry]):
                rejected.append((x, y))
                continue
            parent[ry] = rx
            members[rx] |= members.pop(ry)

        seg_by_key = {s.key: s for s in segments}
        groups: dict[int, _Group] = {}
        for root, keys in members.items():
            parts = [seg_by_key[k] for k in sorted(keys)]
            g = _Group(
                key=root,
                track_ids=sorted({t for p in parts for t in p.track_ids}),
                observations=_dedupe([o for p in parts for o in p.observations]),
                flags=set().union(*(p.flags for p in parts)),
                notes=[n for p in parts for n in p.notes],
            )
            if len(keys) > 1:
                g.flags.add(WagonFlag.DUPLICATE_MERGED)
                g.notes.append(f"concurrent duplicate tracks merged: {g.track_ids}")
            groups[root] = g

        def track_ids_of(*keys: int) -> list[int]:
            return sorted({t for k in keys for t in seg_by_key[k].track_ids})

        for x, y, m in candidate_pairs:
            for k in (x, y):
                groups[find(k)].flags.add(WagonFlag.DUPLICATE_CANDIDATE)
            unresolved.append({
                "type": "duplicate_candidate",
                "track_ids": track_ids_of(x, y),
                "_keys": [find(x), find(y)],
                "detail": f"tracks coexist with mean IoU {m:.2f}; kept as separate wagons",
            })
        for x, y in rejected:
            for k in (x, y):
                groups[find(k)].flags.add(WagonFlag.AMBIGUOUS_IDENTITY)
            unresolved.append({
                "type": "duplicate_conflict",
                "track_ids": track_ids_of(x, y),
                "_keys": [find(x), find(y)],
                "detail": "duplicate-level overlap but merging would join tracks known to be distinct",
            })

        group_cannot: set[frozenset[int]] = set()
        for pair in cannot_link:
            p, q = tuple(pair)
            rp, rq = find(p), find(q)
            if rp != rq:
                group_cannot.add(frozenset((rp, rq)))
        return list(groups.values()), group_cannot

    # ---------------------------------------------------------- fragments
    def _fragment_compatible(self, a: _Group, b: _Group) -> tuple[bool, float, str]:
        """Can group b be a continuation of group a? Returns (ok, normalised distance, reason)."""
        cfg = self.cfg
        margin = self._margin
        gap = b.first.timestamp - a.last.timestamp
        if gap <= 0:
            return False, 0.0, "overlapping in time"
        if gap > cfg.max_gap_seconds:
            return False, 0.0, "gap too long"

        tail = a.observations[-cfg.motion_fit_window:]
        va = motion.velocity(tail, self.frame_size, margin)
        ref_w = max(max(max(o.width, o.height) for o in tail), 1.0)  # largest recent extent ~ least clipped
        threshold = cfg.max_center_distance_ratio * ref_w
        dist_sq = 0.0
        for axis, v in zip(motion.AXES, va):
            pair = motion.common_anchor(a.last, b.first, axis, self.frame_size, margin)
            if pair is None:
                if abs(v) >= cfg.min_speed_px_per_s:
                    # The object moves along this axis but no edge is comparable: cannot verify.
                    return False, float("inf"), f"no comparable edge on moving axis {axis}"
                continue
            dist_sq += (pair[0] + v * gap - pair[1]) ** 2
        dist = dist_sq ** 0.5
        if dist > threshold:
            return False, dist / threshold, f"position mismatch ({dist:.0f}px > {threshold:.0f}px)"

        # Size consistency, per axis, skipped where either box is cut by the frame border.
        r = cfg.max_size_ratio
        for axis, size_a, size_b in (("x", a.last.width, b.first.width), ("y", a.last.height, b.first.height)):
            if any(motion.axis_clipping(a.last, axis, self.frame_size, margin)) or any(
                motion.axis_clipping(b.first, axis, self.frame_size, margin)
            ):
                continue
            if not (1 / r <= max(size_a, 1.0) / max(size_b, 1.0) <= r):
                return False, dist / threshold, f"{'width' if axis == 'x' else 'height'} mismatch"

        # Direction consistency, only when both fragments are clearly moving.
        vb = motion.velocity(b.observations[:cfg.motion_fit_window], self.frame_size, margin)
        for i in (0, 1):
            if abs(va[i]) >= cfg.min_speed_px_per_s and abs(vb[i]) >= cfg.min_speed_px_per_s:
                if (va[i] > 0) != (vb[i] > 0):
                    return False, dist / threshold, "opposite direction"

        # Class: confident and different classes block a merge; same class is not evidence.
        ca = aggregate_class(a.observations, self.class_cfg, self.track_cfg.edge_observation_weight)
        cb = aggregate_class(b.observations, self.class_cfg, self.track_cfg.edge_observation_weight)
        if not ca.uncertain and not cb.uncertain and ca.class_name != cb.class_name:
            return False, dist / threshold, f"confident class conflict ({ca.class_name} vs {cb.class_name})"
        return True, dist / threshold, "ok"

    def _link_fragments(
        self, groups: list[_Group], cannot_link: set[frozenset[int]], unresolved: list[dict[str, Any]]
    ) -> list[_Group]:
        groups = sorted(groups, key=lambda g: (g.first.timestamp, g.key))
        succ: dict[int, list[int]] = {i: [] for i in range(len(groups))}
        pred: dict[int, list[int]] = {i: [] for i in range(len(groups))}
        for i, a in enumerate(groups):
            for j, b in enumerate(groups):
                if i == j or b.first.timestamp <= a.last.timestamp:
                    continue
                if b.first.timestamp - a.last.timestamp > self.cfg.max_gap_seconds:
                    continue
                if frozenset((a.key, b.key)) in cannot_link:
                    continue
                ok, _, reason = self._fragment_compatible(a, b)
                log.debug("fragment %s@%.2f -> %s@%.2f: %s (%s)",
                          a.track_ids, a.last.timestamp, b.track_ids, b.first.timestamp, ok, reason)
                if ok:
                    succ[i].append(j)
                    pred[j].append(i)

        # Transitive reduction: a "skip" link i->j is implied when a valid chain i->k->j exists
        # through an intermediate fragment, so it is not a competing alternative.
        edges = {(i, j) for i, js in succ.items() for j in js}
        redundant = {(i, j) for i, j in edges if any((i, k) in edges and (k, j) in edges for k in succ[i])}
        for i, j in redundant:
            succ[i].remove(j)
            pred[j].remove(i)

        nxt: dict[int, int] = {}
        flagged: set[tuple[int, ...]] = set()
        for i, options in succ.items():
            if not options:
                continue
            if len(options) == 1 and len(pred[options[0]]) == 1:
                nxt[i] = options[0]
                continue
            involved = {i} | set(options) | {k for j in options for k in pred[j]}
            key = tuple(sorted(involved))
            if key in flagged:
                continue
            flagged.add(key)
            for k in involved:
                groups[k].flags.add(WagonFlag.AMBIGUOUS_IDENTITY)
            unresolved.append({
                "type": "ambiguous_fragment",
                "track_ids": sorted({t for k in involved for t in groups[k].track_ids}),
                "_keys": [groups[k].key for k in involved],
                "detail": "several plausible continuations; fragments kept as separate wagons",
            })

        has_pred = set(nxt.values())
        out: list[_Group] = []
        for i, g in enumerate(groups):
            if i in has_pred:
                continue
            chain = [i]
            while chain[-1] in nxt:
                chain.append(nxt[chain[-1]])
            parts = [groups[k] for k in chain]
            if len(parts) == 1:
                merged = g
            else:
                merged = _Group(
                    key=parts[0].key,
                    track_ids=sorted({t for p in parts for t in p.track_ids}),
                    observations=_dedupe([o for p in parts for o in p.observations]),
                    flags=set().union(*(p.flags for p in parts)) | {WagonFlag.FRAGMENT_MERGED},
                    notes=[n for p in parts for n in p.notes]
                    + [f"track fragments linked in time order: {[p.track_ids for p in parts]}"],
                )
            merged.member_keys = {p.key for p in parts}
            out.append(merged)
        return out

    # ------------------------------------------------------------- record
    def _build_record(self, uid: str, g: _Group, decision: ClassDecision) -> WagonRecord:
        flags = set(g.flags)
        notes = list(g.notes)
        if decision.uncertain:
            flags.add(WagonFlag.CLASS_UNCERTAIN)

        status = CountStatus.COUNTED
        duration = g.last.timestamp - g.first.timestamp
        if len(g.observations) < self.cfg.min_observations or duration < self.cfg.min_duration_seconds:
            status = CountStatus.NOT_COUNTED_INSUFFICIENT_EVIDENCE
            flags.add(WagonFlag.INSUFFICIENT_EVIDENCE)
            notes.append(f"{len(g.observations)} observations over {duration:.2f}s is below the counting minimum")

        return WagonRecord(
            wagon_uid=uid,
            track_ids=g.track_ids,
            class_decision=decision,
            first_timestamp=g.first.timestamp,
            last_timestamp=g.last.timestamp,
            first_frame=g.first.frame_index,
            last_frame=g.last.frame_index,
            n_observations=len(g.observations),
            count_status=status,
            flags=flags,
            notes=notes,
        )
