from pathlib import Path

import pytest

from app.core.exceptions import VideoInputError
from app.pipeline.video_reader import SamplingStats, inspect_video, iter_samples
from tests.synthetic import write_video


def _sample(path: Path, target: float, fps: float, max_frames=None):
    stats = SamplingStats()
    samples = [(s.frame_index, s.timestamp, s.sample_index) for s in iter_samples(path, target, fps, max_frames, stats)]
    return samples, stats


def test_inspect_video_reads_metadata(tmp_path: Path):
    p = write_video(tmp_path / "v.mp4", fps=25, n_frames=50)
    meta = inspect_video(p)
    assert (meta.width, meta.height) == (320, 240)
    assert meta.fps == pytest.approx(25, abs=0.01)
    assert meta.frame_count == 50
    assert meta.duration_seconds == pytest.approx(2.0, abs=0.05)


def test_60fps_source_is_subsampled_to_about_30(tmp_path: Path):
    p = write_video(tmp_path / "v60.mp4", fps=60, n_frames=120)
    samples, stats = _sample(p, 30, 60)
    assert stats.decoded_frames == 120
    assert 59 <= len(samples) <= 61
    idx = [s[0] for s in samples]
    assert idx[:4] == [0, 2, 4, 6]  # original indices preserved
    ts = [s[1] for s in samples]
    assert all(b > a for a, b in zip(ts, ts[1:]))
    assert ts[1] == pytest.approx(2 / 60, abs=1e-3)
    assert stats.effective_fps == pytest.approx(30, rel=0.03)


def test_30fps_source_keeps_every_frame(tmp_path: Path):
    p = write_video(tmp_path / "v30.mp4", fps=30, n_frames=45)
    samples, _ = _sample(p, 30, 30)
    assert [s[0] for s in samples] == list(range(45))


def test_25fps_source_is_not_upsampled(tmp_path: Path):
    p = write_video(tmp_path / "v25.mp4", fps=25, n_frames=50)
    samples, stats = _sample(p, 30, 25)
    assert len(samples) == 50  # no duplicated frames
    assert len({s[0] for s in samples}) == 50
    assert samples[10][1] == pytest.approx(10 / 25, abs=1e-3)
    assert stats.effective_fps == pytest.approx(25, rel=0.03)


def test_lower_target_rate_and_sample_indices(tmp_path: Path):
    p = write_video(tmp_path / "v.mp4", fps=30, n_frames=60)
    samples, _ = _sample(p, 10, 30)
    assert [s[0] for s in samples][:4] == [0, 3, 6, 9]
    assert [s[2] for s in samples] == list(range(len(samples)))


def test_max_frames_stops_early(tmp_path: Path):
    p = write_video(tmp_path / "v.mp4", fps=30, n_frames=60)
    samples, stats = _sample(p, 30, 30, max_frames=7)
    assert len(samples) == 7 and stats.stopped_early


def test_missing_and_empty_and_corrupt_inputs(tmp_path: Path):
    with pytest.raises(VideoInputError, match="not found"):
        inspect_video(tmp_path / "missing.mp4")
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(VideoInputError, match="empty"):
        inspect_video(empty)
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"this is not a video" * 100)
    with pytest.raises(VideoInputError):
        inspect_video(junk)
