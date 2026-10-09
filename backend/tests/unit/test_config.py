from pathlib import Path

import pytest

from app.core.exceptions import ConfigError
from app.pipeline.config import PROJECT_ROOT, load_config


def test_default_yaml_loads_and_matches_model_defaults():
    cfg = load_config()
    assert cfg.sampling.target_fps == 30
    assert cfg.counting.mode == "registry"
    assert cfg.resolved_model_path().parent == PROJECT_ROOT / "backend" / "models"


def test_dotted_overrides_apply_and_none_is_ignored(tmp_path: Path):
    cfg = load_config(overrides={"sampling.target_fps": 15, "detector.device": None,
                                 "detector.model_path": str(tmp_path / "m.pt")})
    assert cfg.sampling.target_fps == 15
    assert cfg.detector.device == "auto"
    assert cfg.resolved_model_path() == tmp_path / "m.pt"


def test_relative_paths_resolve_against_project_root():
    cfg = load_config(overrides={"output.output_dir": "data/x"})
    assert cfg.resolved_output_dir() == PROJECT_ROOT / "data" / "x"


@pytest.mark.parametrize("override", [
    {"sampling.target_fps": 0},
    {"counting.mode": "magic"},
    {"detector.unknown_key": 1},
    {"tracker.track_low_thresh": 0.9, "tracker.track_high_thresh": 0.2},
])
def test_invalid_values_raise_config_error(override):
    with pytest.raises(ConfigError):
        load_config(overrides=override)


def test_missing_config_file_raises(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")
