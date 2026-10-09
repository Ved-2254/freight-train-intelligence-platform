"""Full pipeline on a real video with the trained model.

Set WAGON_SAMPLE_VIDEO=<path>. Optionally set WAGON_EXPECTED_COUNT=<int> and
WAGON_EXPECTED_SEQUENCE="Locomotive,BOXN,..." to check against a manual ground truth.
"""

import os
from pathlib import Path

import pytest

from tests.conftest import default_model_path, requires_ultralytics

pytestmark = [requires_ultralytics, pytest.mark.model, pytest.mark.real_video]

VIDEO = os.environ.get("WAGON_SAMPLE_VIDEO")


@pytest.mark.skipif(not VIDEO, reason="WAGON_SAMPLE_VIDEO is not set")
def test_real_video_end_to_end(tmp_path, config):
    from app.pipeline.pipeline import process_video

    if not default_model_path().is_file():
        pytest.skip("model weights not found")
    config.detector.model_path = str(default_model_path())
    result = process_video(Path(VIDEO), config, run_dir=tmp_path / "run")
    assert result.status == "completed"
    assert (tmp_path / "run" / "result.json").is_file()
    assert sum(result.counts.type_counts.values()) == result.counts.total_counted

    expected = os.environ.get("WAGON_EXPECTED_COUNT")
    if expected:
        assert result.counts.total_counted == int(expected)
    seq = os.environ.get("WAGON_EXPECTED_SEQUENCE")
    if seq:
        assert [s.class_name for s in result.sequence] == [c.strip() for c in seq.split(",")]
