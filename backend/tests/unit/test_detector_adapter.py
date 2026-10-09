from pathlib import Path

import numpy as np
import pytest

from app.core.exceptions import InferenceError, ModelLoadError
from app.pipeline.config import DetectorConfig
from app.pipeline.detector import UltralyticsDetector, normalize_detections

NAMES = {0: "BCN", 1: "BOXN"}


def test_empty_output_normalizes_to_empty_list():
    out = normalize_detections(np.zeros((0, 4)), np.zeros(0), np.zeros(0), NAMES, 5, 0.2, 640, 360)
    assert out == []


def test_boxes_are_clipped_named_and_carry_frame_info():
    xyxy = np.array([[-10, 5, 100, 50], [600, 300, 700, 400]])
    out = normalize_detections(xyxy, np.array([0.9, 0.4]), np.array([1, 0]), NAMES, 12, 0.4, 640, 360)
    assert len(out) == 2
    assert out[0].bbox == (0.0, 5.0, 100.0, 50.0)
    assert out[0].class_name == "BOXN" and out[0].class_id == 1
    assert out[1].bbox == (600.0, 300.0, 640.0, 360.0)
    assert out[1].frame_index == 12 and out[1].timestamp == 0.4
    assert out[1].confidence == pytest.approx(0.4)


def test_degenerate_boxes_are_dropped():
    out = normalize_detections(np.array([[700, 10, 800, 20]]), np.array([0.9]), np.array([0]), NAMES, 0, 0, 640, 360)
    assert out == []


def test_unknown_class_id_is_an_error_not_a_guess():
    with pytest.raises(InferenceError):
        normalize_detections(np.array([[0, 0, 10, 10]]), np.array([0.9]), np.array([7]), NAMES, 0, 0, 640, 360)


def test_missing_weights_raise_model_load_error(tmp_path: Path):
    with pytest.raises(ModelLoadError, match="not found"):
        UltralyticsDetector(DetectorConfig(), tmp_path / "missing.pt")


def test_non_pt_extension_is_rejected(tmp_path: Path):
    f = tmp_path / "weights.onnx"
    f.write_bytes(b"x")
    with pytest.raises(ModelLoadError, match="extension"):
        UltralyticsDetector(DetectorConfig(), f)
