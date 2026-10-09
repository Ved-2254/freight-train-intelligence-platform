import io
import json
import os
import time

import pytest

from app.core.exceptions import (
    InferenceError,
    JobCancelledError,
    ModelLoadError,
    OutputWriteError,
    TrackingError,
    VideoInputError,
)
from app.pipeline.models import ProgressEvent
from app.services.result_service import public_result, scrub_paths
from app.storage.file_storage import LocalFileStorage, UnsafeStorageKey, UploadTooLarge
from app.workers.pipeline_runner import OPTION_TO_CONFIG, PipelineRunner, ProgressMapper, classify_error
from tests.api.conftest import TRAIN, make_settings
from tests.conftest import CLASS_NAMES
from tests.synthetic import ScriptedDetector


# ------------------------------------------------------------------ storage
@pytest.fixture
def storage(tmp_path):
    s = LocalFileStorage(tmp_path / "root")
    s.initialize()
    return s


@pytest.mark.parametrize("key", [
    "../outside.txt", "uploads/../../x", "/etc/passwd", "C:/Windows/x", "uploads\\..\\x", "", "uploads//x", "a/\x00b",
])
def test_resolve_rejects_unsafe_keys(storage, key):
    with pytest.raises(UnsafeStorageKey):
        storage.resolve(key)


def test_resolve_accepts_generated_keys(storage):
    p = storage.resolve(storage.job_output_key("job_" + "a" * 32))
    assert storage.root in p.parents


def test_write_stream_enforces_limit_and_cleans_up(storage):
    dest = storage.new_temporary_path(".mp4")
    with pytest.raises(UploadTooLarge):
        storage.write_stream(io.BytesIO(b"x" * 5000), dest, max_bytes=1000)
    assert not dest.exists()
    assert storage.write_stream(io.BytesIO(b"x" * 500), dest, max_bytes=1000) == 500


def test_move_never_overwrites(storage):
    a = storage.new_temporary_path()
    a.write_bytes(b"1")
    storage.move_into(a, "uploads/vid_x.mp4")
    b = storage.new_temporary_path()
    b.write_bytes(b"2")
    with pytest.raises(Exception):
        storage.move_into(b, "uploads/vid_x.mp4")
    assert storage.resolve("uploads/vid_x.mp4").read_bytes() == b"1"


def test_cleanup_temporary_only_removes_old_files(storage):
    old, new = storage.new_temporary_path(), storage.new_temporary_path()
    old.write_bytes(b"o")
    new.write_bytes(b"n")
    past = time.time() - 7200
    os.utime(old, (past, past))
    assert storage.cleanup_temporary(3600) == 1
    assert not old.exists() and new.exists()


# ------------------------------------------------------------ path scrubbing
def test_scrub_paths_removes_windows_and_posix_paths_but_keeps_urls():
    raw = {
        "input": {"path": "D:\\PROJECTS\\SGP 2.0\\Raw Video\\YT-073.mp4"},
        "model": {"model_path": "D:\\PROJECTS\\x\\backend\\models\\best.pt", "docs": "https://docs.ultralytics.com/a/b"},
        "error": "VideoInputError: Input video not found: C:/data/uploads/vid_1.mp4",
        "posix": "/home/user/storage/jobs/x/result.json",
        "relative": "backend/models/best.pt",
        "list": ["E:\\a\\b.csv", 3, None],
    }
    out = scrub_paths(raw)
    assert out["input"]["path"] == "YT-073.mp4"
    assert out["model"]["model_path"] == "best.pt"
    assert out["model"]["docs"] == "https://docs.ultralytics.com/a/b"
    assert out["error"] == "VideoInputError: Input video not found: vid_1.mp4"
    assert out["posix"] == "result.json"
    assert out["relative"] == "backend/models/best.pt"
    assert out["list"] == ["b.csv", 3, None]
    assert public_result(raw, "my video.mp4")["input"]["path"] == "my video.mp4"


# ------------------------------------------------------------------- runner
def test_progress_mapper_is_honest_and_monotonic():
    m = ProgressMapper()
    assert m.map(ProgressEvent("validating", "v"))[1] == 0.0
    assert m.map(ProgressEvent("detecting_and_tracking", "d", 50, 100))[1] == pytest.approx(45.0)
    stage, pct, msg = m.map(ProgressEvent("detecting_and_tracking", "d", 75, None))
    assert pct is None and "frame 75" in msg  # unknown total: no invented percentage
    assert m.map(ProgressEvent("resolving", "r"))[1] == 86.0
    assert m.map(ProgressEvent("rendering", "r", 10, 100))[1] == pytest.approx(89.1)
    assert m.map(ProgressEvent("validating", "late event"))[1] == pytest.approx(89.1)  # never goes backwards


@pytest.mark.parametrize("exc, code", [
    (VideoInputError("x"), "INVALID_VIDEO"),
    (ModelLoadError("x"), "MODEL_UNAVAILABLE"),
    (InferenceError("x"), "INFERENCE_FAILED"),
    (TrackingError("x"), "TRACKING_FAILED"),
    (OutputWriteError("x"), "OUTPUT_WRITE_FAILED"),
    (OSError(28, "No space left on device"), "INSUFFICIENT_STORAGE"),
    (ValueError("x"), "INTERNAL_ERROR"),
])
def test_classify_error(exc, code):
    assert classify_error(exc)[0] == code


def test_runner_maps_only_whitelisted_options(tmp_path):
    runner = PipelineRunner(make_settings(tmp_path))
    cfg = runner.build_config({"target_fps": 12, "counting_mode": "line", "write_video": False})
    assert cfg.sampling.target_fps == 12 and cfg.counting.mode == "line" and cfg.output.write_video is False
    assert cfg.resolved_model_path().name == "best.pt"  # always the server-side model
    from app.core.exceptions import ConfigError

    with pytest.raises(ConfigError):
        runner.build_config({"model_path": "x.pt"})
    assert set(OPTION_TO_CONFIG) == {"target_fps", "confidence_threshold", "counting_mode", "line_position",
                                     "travel_axis", "write_video"}


def test_runner_reuses_loaded_detector(tmp_path):
    loads = []

    def factory(cfg):
        loads.append(1)
        return ScriptedDetector(TRAIN, CLASS_NAMES)

    runner = PipelineRunner(make_settings(tmp_path), detector_factory=factory)
    a = runner.detector_for(runner.build_config({"target_fps": 10}))
    b = runner.detector_for(runner.build_config({"target_fps": 20}))  # sampling change: same model
    c = runner.detector_for(runner.build_config({"confidence_threshold": 0.5}))  # detector change: reload
    assert a is b and b is not c and len(loads) == 2


def test_pipeline_cancellation_hook(tmp_path, train_video):
    from app.pipeline.config import load_config
    from app.pipeline.pipeline import process_video

    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 3

    with pytest.raises(JobCancelledError):
        process_video(train_video, load_config(), run_dir=tmp_path / "run",
                      detector=ScriptedDetector(TRAIN, CLASS_NAMES), should_cancel=should_cancel)
    result = json.loads((tmp_path / "run" / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "cancelled"
