"""Identity-resolution rules. Tracks are sampled at 10 fps; boxes move +20 px/sample (200 px/s)."""

from app.pipeline.config import ClassConfig, CountingConfig, ResolutionConfig, TrackConfig
from app.pipeline.models import CountStatus, WagonFlag
from app.pipeline.wagon_registry import WagonRegistry
from tests.synthetic import make_track, moving_boxes

V = 20.0  # px per sample


def _registry(**res):
    return WagonRegistry(ResolutionConfig(**res), TrackConfig(), ClassConfig(), CountingConfig(boundary_seconds=0.0))


def _resolve(tracks, frame_size=None, **res):
    return _registry(**res).resolve(tracks, frame_size)


def test_one_track_one_wagon():
    r = _resolve([make_track(1, 0, moving_boxes(0, 10, V), "BOXN")])
    assert len(r.wagons) == 1
    w = r.wagons[0]
    assert w.wagon_uid == "W001" and w.track_ids == [1] and w.class_name == "BOXN"
    assert w.count_status == CountStatus.COUNTED and not w.flags


def test_fragment_after_occlusion_is_linked():
    a = make_track(1, 0, moving_boxes(0, 10, V), "BOXN")  # samples 0..9
    b = make_track(7, 14, moving_boxes(14 * V, 10, V), "BOXN")  # resumes where motion predicts
    r = _resolve([a, b])
    assert len(r.wagons) == 1
    assert r.wagons[0].track_ids == [1, 7]
    assert WagonFlag.FRAGMENT_MERGED in r.wagons[0].flags
    assert r.track_to_wagons == {1: ["W001"], 7: ["W001"]}


def test_coexisting_tracks_are_never_merged():
    a = make_track(1, 0, moving_boxes(0, 10, V), "BOXN")
    b = make_track(2, 0, moving_boxes(-170, 10, V), "BOXN")  # neighbouring wagon, same class
    r = _resolve([a, b])
    assert len(r.wagons) == 2
    assert not any(WagonFlag.FRAGMENT_MERGED in w.flags for w in r.wagons)


def test_same_class_and_close_in_time_is_not_enough():
    a = make_track(1, 0, moving_boxes(0, 10, V), "BOXN")  # ends at x=180
    b = make_track(2, 11, moving_boxes(-150, 10, V), "BOXN")  # next wagon entering far behind
    r = _resolve([a, b])
    assert len(r.wagons) == 2


def test_gap_longer_than_limit_is_not_linked():
    a = make_track(1, 0, moving_boxes(0, 10, V), "BOXN")
    b = make_track(2, 40, moving_boxes(40 * V, 10, V), "BOXN")  # 3.0 s later
    assert len(_resolve([a, b], max_gap_seconds=1.5).wagons) == 2


def test_confident_class_conflict_blocks_merge():
    a = make_track(1, 0, moving_boxes(0, 10, V), "BOXN")
    b = make_track(2, 13, moving_boxes(13 * V, 10, V), "BCN")
    r = _resolve([a, b])
    assert len(r.wagons) == 2


def test_chain_of_fragments_is_linked_without_false_ambiguity():
    a = make_track(1, 0, moving_boxes(0, 10, V), "BOXN")
    b = make_track(2, 12, moving_boxes(12 * V, 2, V), "BOXN")  # short fragment
    c = make_track(3, 15, moving_boxes(15 * V, 8, V), "BOXN")  # fits a directly and via b
    r = _resolve([a, b, c])
    assert len(r.wagons) == 1 and r.wagons[0].track_ids == [1, 2, 3]
    assert not r.unresolved


def test_concurrent_competing_continuations_are_flagged_not_merged():
    a = make_track(1, 0, moving_boxes(0, 10, V), "BOXN")
    b = make_track(2, 13, moving_boxes(13 * V, 8, V), "BOXN")  # exactly where a predicts
    c = make_track(3, 13, moving_boxes(13 * V + 60, 8, V), "BOXN")  # also within tolerance, coexists with b
    r = _resolve([a, b, c])
    assert len(r.wagons) == 3
    assert all(WagonFlag.AMBIGUOUS_IDENTITY in w.flags for w in r.wagons)
    frag = next(u for u in r.unresolved if u["type"] == "ambiguous_fragment")
    assert set(frag["wagon_uids"]) == {"W001", "W002", "W003"}


def test_concurrent_duplicate_boxes_are_merged():
    a = make_track(1, 0, moving_boxes(0, 10, V), "BOXN")
    b = make_track(2, 1, moving_boxes(V + 3, 8, V), "BOXN")  # nearly identical box, same wagon
    r = _resolve([a, b])
    assert len(r.wagons) == 1
    assert WagonFlag.DUPLICATE_MERGED in r.wagons[0].flags
    assert r.wagons[0].n_observations == 10  # deduplicated per sample


def test_partial_overlap_is_only_a_duplicate_candidate():
    a = make_track(1, 0, moving_boxes(0, 10, V), "BOXN")
    b = make_track(2, 0, moving_boxes(70, 10, V), "BOXN")  # IoU ~0.37
    r = _resolve([a, b])
    assert len(r.wagons) == 2
    assert all(WagonFlag.DUPLICATE_CANDIDATE in w.flags for w in r.wagons)
    assert r.unresolved[0]["type"] == "duplicate_candidate"


def test_short_tracks_are_reported_but_not_counted():
    r = _resolve([make_track(1, 0, moving_boxes(0, 2, V), "BOXN")])
    assert r.wagons[0].count_status == CountStatus.NOT_COUNTED_INSUFFICIENT_EVIDENCE
    assert WagonFlag.INSUFFICIENT_EVIDENCE in r.wagons[0].flags


def test_fragment_of_wagon_entering_frame_is_linked_despite_clipped_boxes():
    # Wagon enters from the left edge (boxes clipped, centre moves at half speed), is lost for
    # 1.2 s, then reappears mid-frame. Only the unclipped right edge gives the true speed.
    frame = (640, 360)
    full = [(x - 150, 100.0, x, 220.0) for x in (20.0 + 20 * i for i in range(30))]
    clipped = [(max(0.0, b[0]), b[1], b[2], b[3]) for b in full]
    a = make_track(1, 0, clipped[:6], "BOXN")  # samples 0-5, all touching the left edge
    b = make_track(2, 18, clipped[18:30], "BOXN")  # after a 1.2 s gap, fully visible
    r = _resolve([a, b], frame_size=frame)
    assert len(r.wagons) == 1 and r.wagons[0].track_ids == [1, 2]


def test_resolution_is_deterministic():
    tracks = [
        make_track(1, 0, moving_boxes(0, 10, V), "BOXN"),
        make_track(5, 14, moving_boxes(14 * V, 10, V), "BOXN"),
        make_track(3, 0, moving_boxes(-170, 25, V), "BCN"),
    ]
    a = _resolve(tracks)
    b = _resolve(list(reversed(tracks)))
    assert [(w.wagon_uid, w.track_ids, w.class_name) for w in a.wagons] == \
           [(w.wagon_uid, w.track_ids, w.class_name) for w in b.wagons]


def test_sudden_jump_splits_the_track_into_two_wagons():
    boxes = moving_boxes(0, 10, V)
    boxes[6:] = [(x1 + 170, y1, x2 + 170, y2) for x1, y1, x2, y2 in boxes[6:]]
    r = _resolve([make_track(1, 0, boxes, "BOXN")])
    assert len(r.wagons) == 2
    assert all(WagonFlag.POSSIBLE_ID_SWITCH in w.flags for w in r.wagons)
    assert r.track_to_wagons[1] == ["W001", "W002"]


def test_tracker_id_hopping_between_wagons_is_split_and_relinked():
    # Wagon A tracked as id 1, wagon B (170 px behind) as id 2 until it reaches x=200, then the
    # tracker hands id 1 to wagon B (an ID hop after A left). B's later part must rejoin id 2.
    a = moving_boxes(300, 10, V)  # samples 0-9
    b_first = moving_boxes(130, 4, V)  # samples 0-3 (id 2)
    b_later = moving_boxes(130 + 6 * V, 8, V)  # samples 6-13, continues B's motion
    t1 = make_track(1, 0, a, "BOXN")
    hop = make_track(1, 10, moving_boxes(130 + 10 * V, 4, V), "BCN")  # id 1 reused on B at samples 10-13
    t1.observations += hop.observations
    t2 = make_track(2, 0, b_first, "BCN")
    t3 = make_track(3, 6, b_later[:4], "BCN")  # samples 6-9
    r = _resolve([t1, t2, t3])
    by_class = sorted((w.class_name, w.track_ids) for w in r.wagons if w.counted)
    assert len(r.wagons) == 2
    assert by_class == [("BCN", [1, 2, 3]), ("BOXN", [1])]
