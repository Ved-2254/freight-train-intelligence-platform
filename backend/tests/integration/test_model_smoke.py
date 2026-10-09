"""Loads the configured trained weights and runs inference on a synthetic frame.

This validates loading, the class map and the output format - not detection accuracy.
Skipped when Ultralytics or the weights are unavailable.
"""

import numpy as np
import pytest

from app.pipeline.config import DetectorConfig
from tests.conftest import default_model_path, requires_ultralytics

pytestmark = [requires_ultralytics, pytest.mark.model]

MODEL = default_model_path()


@pytest.fixture(scope="module")
def detector():
    if not MODEL.is_file():
        pytest.skip(f"model weights not found at {MODEL}")
    from app.pipeline.detector import UltralyticsDetector

    return UltralyticsDetector(DetectorConfig(device="cpu"), MODEL)


def test_model_loads_with_its_own_class_map(detector):
    info = detector.info()
    assert info["num_classes"] == len(detector.class_names) > 0
    assert list(detector.class_names) == list(range(len(detector.class_names)))
    assert info["sha256"] and info["framework_version"]


def test_inference_returns_normalized_detections(detector):
    frame = np.full((360, 640, 3), 127, dtype=np.uint8)
    dets = detector.detect(frame, frame_index=3, timestamp=0.1)
    assert isinstance(dets, list)
    for d in dets:
        assert d.class_name in detector.class_names.values()
        assert 0 <= d.bbox[0] < d.bbox[2] <= 640 and 0 <= d.bbox[1] < d.bbox[3] <= 360
        assert d.frame_index == 3


def test_expected_classes_guard(detector):
    from app.core.exceptions import ModelClassMismatchError
    from app.pipeline.detector import UltralyticsDetector

    actual = [detector.class_names[k] for k in sorted(detector.class_names)]
    UltralyticsDetector(DetectorConfig(device="cpu", expected_classes=actual), MODEL)
    with pytest.raises(ModelClassMismatchError):
        UltralyticsDetector(DetectorConfig(device="cpu", expected_classes=list(reversed(actual))), MODEL)
