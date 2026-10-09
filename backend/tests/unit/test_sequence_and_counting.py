from app.pipeline.config import ClassConfig, CountingConfig, ResolutionConfig, TrackConfig
from app.pipeline.models import CountStatus, WagonFlag
from app.pipeline.sequence_builder import analyze_motion, build_sequence
from app.pipeline.wagon_counter import apply_line_counting, calculate_counts
from app.pipeline.wagon_registry import WagonRegistry
from tests.synthetic import make_track, moving_boxes

FRAME = (640, 360)


def _train(direction: int = 1, classes=("Locomotive", "BOXN", "BCN", "BOXN"), n=40):
    """Consecutive wagons, all visible at once over time; wagon 0 leads in the travel direction."""
    v = 20.0 * direction
    tracks = []
    for k, cls in enumerate(classes):
        start_x = (100 - 170 * k) if direction > 0 else (400 + 170 * k)
        tracks.append(make_track(10 + k, 0, moving_boxes(start_x, n, v), cls))
    return tracks


def _pipeline(tracks, counting=None, start=-10.0, end=100.0):
    counting = counting or CountingConfig(boundary_seconds=0.0)
    res = ResolutionConfig()
    reg = WagonRegistry(res, TrackConfig(), ClassConfig(), counting).resolve(tracks, FRAME)
    motion = analyze_motion(reg.wagons, reg.observations, FRAME, counting, res, video_span=(start, end))
    if counting.mode == "line":
        apply_line_counting(reg.wagons)
    counts = calculate_counts(reg.wagons, counting, len(tracks))
    seq, info = build_sequence(reg.wagons, reg.observations, motion, counting)
    return reg, motion, counts, seq, info


def test_left_to_right_passage_order_is_leading_wagon_first():
    _, motion, counts, seq, info = _pipeline(_train(+1))
    assert motion.axis == "x" and motion.direction == 1
    assert [s.class_name for s in seq] == ["Locomotive", "BOXN", "BCN", "BOXN"]
    assert info["travel_direction"] == "left_to_right"
    assert info["convention"] == "passage_order_at_reference_line"
    assert counts.total_counted == 4


def test_right_to_left_passage_order():
    _, motion, _, seq, info = _pipeline(_train(-1))
    assert motion.direction == -1
    assert [s.class_name for s in seq] == ["Locomotive", "BOXN", "BCN", "BOXN"]
    assert info["travel_direction"] == "right_to_left"


def test_order_does_not_depend_on_track_ids_or_input_order():
    tracks = _train(+1)
    for i, t in enumerate(reversed(tracks)):  # leading wagon gets the highest tracker id
        for j, o in enumerate(t.observations):
            object.__setattr__(o, "track_id", 100 - i)
        t.track_id = 100 - i
    _, _, _, seq, _ = _pipeline(list(reversed(tracks)))
    assert [s.class_name for s in seq] == ["Locomotive", "BOXN", "BCN", "BOXN"]


def test_type_counts_reconcile_with_total_including_unresolved():
    tracks = _train(+1)
    tracks.append(make_track(99, 0, moving_boxes(100 - 170 * 4, 40, 20.0),
                             ["BOXN", "BCN", "BTPN", "BLC"] * 10))
    _, _, counts, seq, _ = _pipeline(tracks)
    assert counts.total_counted == 5
    assert counts.type_counts["Unresolved"] == 1
    assert sum(counts.type_counts.values()) == counts.total_counted
    assert seq[-1].uncertain


def test_excluded_classes_give_wagons_only_total():
    counting = CountingConfig(boundary_seconds=0.0, exclude_from_wagon_total=["Locomotive"])
    _, _, counts, _, _ = _pipeline(_train(+1), counting)
    assert counts.total_counted == 4 and counts.wagons_only_total == 3


def test_line_mode_counts_only_validated_crossings():
    tracks = _train(+1)
    # A wagon that stays left of the mid-frame line (x centre < 320) never crosses it.
    tracks.append(make_track(50, 0, moving_boxes(-300, 10, 20.0), "BCN"))
    counting = CountingConfig(mode="line", boundary_seconds=0.0)
    reg, _, counts, seq, info = _pipeline(tracks, counting)
    crossed = [w for w in reg.wagons if w.crossing_time is not None]
    assert counts.total_counted == len(crossed)
    stuck = next(w for w in reg.wagons if 50 in w.track_ids)
    assert stuck.count_status == CountStatus.NOT_COUNTED_NO_LINE_CROSSING
    assert info["convention"] == "line_crossing_order"
    times = [s.crossing_time for s in seq]
    assert times == sorted(times)


def test_jitter_around_line_is_not_a_crossing():
    boxes = [(245 + (4 if i % 2 else -4), 100, 395 + (4 if i % 2 else -4), 220) for i in range(30)]
    tracks = _train(+1) + [make_track(60, 0, boxes, "BOXN")]
    counting = CountingConfig(mode="line", boundary_seconds=0.0, hysteresis_px=10)
    reg, _, _, _, _ = _pipeline(tracks, counting)
    jitter = next(w for w in reg.wagons if 60 in w.track_ids)
    assert jitter.crossing_time is None and not jitter.counted


def test_partial_and_extrapolated_flags_and_completeness():
    counting = CountingConfig(boundary_seconds=0.5)
    reg, _, _, seq, info = _pipeline(_train(+1, n=10), counting, start=0.0, end=0.9)
    assert info["completeness"] == "partial_both"
    assert any(WagonFlag.SEQUENCE_EXTRAPOLATED in w.flags for w in reg.wagons)


def test_wagon_entering_at_edge_early_is_not_partial():
    # Seen 0.1 s after the start but touching the entry (left) edge: its passage is fully observed.
    boxes = [(0.0, 100.0, 40.0 + 20 * i, 220.0) if 40 + 20 * i < 150 else (40.0 + 20 * i - 150, 100.0, 40.0 + 20 * i, 220.0)
             for i in range(40)]
    counting = CountingConfig(boundary_seconds=0.5)
    reg, _, _, _, info = _pipeline([make_track(1, 1, boxes, "BOXN")], counting, start=0.0, end=10.0)
    assert WagonFlag.PARTIAL_AT_START not in reg.wagons[0].flags
    assert info["completeness"] == "complete"


def test_stationary_scene_falls_back_to_spatial_order():
    tracks = [make_track(1, 0, moving_boxes(300, 20, 0.0), "BCN"),
              make_track(2, 0, moving_boxes(100, 20, 0.0), "BOXN")]
    _, motion, _, seq, info = _pipeline(tracks)
    assert motion.direction == 0
    assert info["convention"] == "spatial_order_along_axis"
    assert [s.class_name for s in seq] == ["BOXN", "BCN"]


def test_opposite_mover_is_flagged_direction_inconsistent():
    tracks = _train(+1) + [make_track(70, 0, moving_boxes(500, 20, -20.0), "BCN")]
    reg, motion, _, seq, _ = _pipeline(tracks)
    odd = next(w for w in reg.wagons if 70 in w.track_ids)
    assert WagonFlag.DIRECTION_INCONSISTENT in odd.flags
    assert odd.wagon_uid in motion.inconsistent_wagons


def test_parked_object_on_another_track_is_reported_but_not_counted():
    tracks = _train(+1)
    # A coach parked in the background: almost no motion while the train passes.
    parked = [(700 + (i % 3), 20.0, 1000 + (i % 3), 80.0) for i in range(30)]
    tracks.append(make_track(80, 0, parked, "Locomotive"))
    counting = CountingConfig(boundary_seconds=0.0)
    res = ResolutionConfig()
    reg = WagonRegistry(res, TrackConfig(), ClassConfig(), counting).resolve(tracks, (1280, 720))
    analyze_motion(reg.wagons, reg.observations, (1280, 720), counting, res)
    from app.pipeline.wagon_counter import apply_stationary_exclusion

    apply_stationary_exclusion(reg.wagons)
    counts = calculate_counts(reg.wagons, counting, len(tracks))
    parked_rec = next(w for w in reg.wagons if 80 in w.track_ids)
    assert WagonFlag.STATIONARY_OBJECT in parked_rec.flags
    assert parked_rec.count_status == CountStatus.NOT_COUNTED_STATIONARY
    assert counts.total_counted == 4 and counts.not_counted == 1
    assert not any(WagonFlag.STATIONARY_OBJECT in w.flags for w in reg.wagons if 80 not in w.track_ids)


def test_stopped_train_is_not_excluded_as_stationary():
    tracks = [make_track(1, 0, moving_boxes(300, 20, 0.0), "BCN"),
              make_track(2, 0, moving_boxes(100, 20, 0.0), "BOXN")]
    reg, _, counts, _, _ = _pipeline(tracks)
    assert counts.total_counted == 2
    assert not any(WagonFlag.STATIONARY_OBJECT in w.flags for w in reg.wagons)
