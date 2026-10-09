"""End-to-end pipeline on a synthetic video with a scripted detector and the real ByteTrack.

Model-independent: verifies orchestration, counting, sequencing and outputs, not the detector.
"""

import csv
import json
from pathlib import Path

import cv2
import pytest

from app.core.exceptions import VideoInputError
from app.pipeline.pipeline import process_video
from tests.conftest import CLASS_NAMES, requires_ultralytics
from tests.synthetic import ScriptedDetector, SyntheticTrain, write_video

pytestmark = requires_ultralytics

FPS = 20.0


def _run(tmp_path: Path, config, train: SyntheticTrain, noise=None, **cfg_changes):
    n = int(train.duration_to_clear() * FPS) + 10
    video = write_video(tmp_path / "train.mp4", FPS, n, train.frame_size, train)
    for dotted, value in cfg_changes.items():
        section, key = dotted.split("__")
        setattr(getattr(config, section), key, value)
    det = ScriptedDetector(train, CLASS_NAMES, noise)
    events = []
    result = process_video(video, config, run_dir=tmp_path / "run", detector=det, progress=events.append)
    return result, det, events, tmp_path / "run"


def test_full_passage_counts_and_orders_wagons(tmp_path, config):
    classes = ["Locomotive", "BOXN", "BCN", "BOXN", "BCN"]
    train = SyntheticTrain(classes=classes, start_x=-10)
    result, det, events, out = _run(tmp_path, config, train)

    assert result.status == "completed"
    assert result.counts.total_counted == 5
    assert result.counts.type_counts == {"BCN": 2, "BOXN": 2, "Locomotive": 1}
    assert [s.class_name for s in result.sequence] == classes
    assert result.sequence_info["travel_direction"] == "left_to_right"
    assert result.sequence_info["completeness"] == "complete"
    assert det.calls == result.sampling["sampled_frames"]
    assert events[-1].stage == "completed"

    for name in ("result.json", "wagons.csv", "tracks.csv", "annotated.mp4", "run.log", "summary.txt"):
        assert (out / name).is_file(), name
    data = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert data["status"] == "completed" and data["counts"]["total_counted"] == 5
    with (out / "wagons.csv").open(encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == len(data["wagons"])
    cap = cv2.VideoCapture(str(out / "annotated.mp4"))
    try:
        assert cap.isOpened()
        assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == result.sampling["sampled_frames"]
    finally:
        cap.release()


def test_occlusion_longer_than_track_buffer_is_resolved_to_one_wagon(tmp_path, config):
    classes = ["Locomotive", "BOXN", "BCN"]
    # Wagon 1 undetected for 1.2 s mid-frame: ByteTrack (buffer 0.5 s) will drop the track.
    train = SyntheticTrain(classes=classes, hidden={1: [(2.2, 3.4)]}, speed=150)
    result, *_ = _run(tmp_path, config, train, tracker__track_buffer_seconds=0.5)
    assert result.counts.total_counted == 3
    assert [s.class_name for s in result.sequence] == classes
    w = next(w for w in result.wagons if w.sequence_position == 2)
    assert len(w.track_ids) >= 2, "occluded wagon should have been tracked as fragments and re-linked"


def test_label_noise_is_stabilised(tmp_path, config):
    classes = ["BOXN", "BCN"]
    train = SyntheticTrain(classes=classes)
    noise = {(0, i): "BCN" for i in range(0, 400, 7)}  # every 7th frame mislabels wagon 0
    result, *_ = _run(tmp_path, config, train, noise=noise)
    assert [s.class_name for s in result.sequence] == classes


def test_target_fps_subsamples_and_preserves_indices(tmp_path, config):
    train = SyntheticTrain(classes=["BOXN", "BCN"])
    result, det, *_ = _run(tmp_path, config, train, sampling__target_fps=10.0)
    s = result.sampling
    assert s["sampled_frames"] == pytest.approx(s["decoded_frames"] / 2, abs=1)
    assert s["effective_fps"] == pytest.approx(10.0, rel=0.05)
    assert result.counts.total_counted == 2


def test_train_already_in_view_is_marked_partial(tmp_path, config):
    train = SyntheticTrain(classes=["BOXN", "BCN", "BOXN"], start_x=500)
    result, *_ = _run(tmp_path, config, train)
    assert result.sequence_info["completeness"] in ("partial_start", "partial_both")
    assert any("completeness" in w for w in result.warnings)


def test_bad_input_writes_failed_result(tmp_path, config):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(VideoInputError):
        process_video(bad, config, run_dir=tmp_path / "run", detector=ScriptedDetector(SyntheticTrain(["BOXN"]), CLASS_NAMES))
    data = json.loads((tmp_path / "run" / "result.json").read_text(encoding="utf-8"))
    assert data["status"] == "failed" and "VideoInputError" in data["error"]
