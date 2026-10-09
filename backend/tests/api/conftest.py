"""Fixtures for API / worker tests: isolated storage + database per test, no embedded worker.

The worker fixture runs the REAL pipeline (`process_video`, real ByteTrack, real resolution,
rendering and exports) with a scripted detector on a synthetic video, so no GPU or model
inference is needed for routine tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import ServiceSettings
from app.main import create_app
from app.repositories.database import Database
from app.storage.file_storage import LocalFileStorage
from app.workers.pipeline_runner import PipelineRunner
from app.workers.video_worker import VideoWorker
from tests.conftest import CLASS_NAMES
from tests.synthetic import ScriptedDetector, SyntheticTrain, write_video

TRAIN = SyntheticTrain(classes=["Locomotive", "BOXN", "BCN"], speed=220)
FPS = 20.0


def make_settings(tmp_path: Path, **overrides) -> ServiceSettings:
    values = dict(
        storage_root=tmp_path / "storage",
        start_embedded_worker=False,
        min_free_disk_bytes=0,
        progress_write_interval=0,
        cancel_check_interval=0,
        cors_origins="http://localhost:3000",
        log_level="WARNING",
    )
    values.update(overrides)
    return ServiceSettings(_env_file=None, **values)


@pytest.fixture
def settings(tmp_path: Path) -> ServiceSettings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: ServiceSettings):
    with TestClient(create_app(settings, start_worker=False)) as c:
        yield c


@pytest.fixture(scope="session")
def train_video(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("videos") / "train.mp4"
    n = int(TRAIN.duration_to_clear() * FPS) + 10
    return write_video(path, FPS, n, TRAIN.frame_size, TRAIN)


def scripted_runner(settings: ServiceSettings) -> PipelineRunner:
    return PipelineRunner(settings, detector_factory=lambda cfg: ScriptedDetector(TRAIN, CLASS_NAMES))


@pytest.fixture
def worker(settings: ServiceSettings) -> VideoWorker:
    w = VideoWorker(settings, Database(settings.db_path), LocalFileStorage(settings.storage_root),
                    scripted_runner(settings), worker_id="test-worker")
    w.initialize()
    return w


def upload(client: TestClient, path: Path, name: str | None = None, content_type: str = "video/mp4"):
    with open(path, "rb") as f:
        return client.post("/api/v1/videos", files={"file": (name or path.name, f, content_type)})


def upload_ok(client: TestClient, path: Path) -> str:
    r = upload(client, path)
    assert r.status_code == 201, r.text
    return r.json()["video_id"]


def create_job(client: TestClient, video_id: str, options: dict | None = None, headers: dict | None = None):
    body = {"video_id": video_id}
    if options is not None:
        body["options"] = options
    return client.post("/api/v1/jobs", json=body, headers=headers or {})
