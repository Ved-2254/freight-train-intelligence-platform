from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from app.pipeline.config import BACKEND_DIR, PipelineConfig, load_config

CLASS_NAMES = {0: "BCN", 1: "BOXN", 2: "Locomotive"}

HAS_ULTRALYTICS = importlib.util.find_spec("ultralytics") is not None
requires_ultralytics = pytest.mark.skipif(not HAS_ULTRALYTICS, reason="ultralytics is not installed")


def default_model_path() -> Path:
    env = os.environ.get("WAGON_MODEL_PATH")
    return Path(env) if env else load_config().resolved_model_path()


@pytest.fixture
def config(tmp_path: Path) -> PipelineConfig:
    cfg = load_config(BACKEND_DIR / "configs" / "default.yaml")
    cfg.output.output_dir = str(tmp_path / "outputs")
    return cfg
