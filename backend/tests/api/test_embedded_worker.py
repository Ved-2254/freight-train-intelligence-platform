"""The single-command mode: the API starts, supervises and stops the worker process."""

import time

from fastapi.testclient import TestClient

from app.main import create_app
from tests.api.conftest import make_settings


def test_api_starts_and_stops_embedded_worker(tmp_path):
    app = create_app(make_settings(tmp_path, heartbeat_seconds=0.5), start_worker=True)
    with TestClient(app) as c:
        deadline = time.time() + 60
        while time.time() < deadline:  # worker imports the pipeline (torch) before its first heartbeat
            if c.get("/api/v1/ready").json()["worker"]["alive"]:
                break
            time.sleep(0.5)
        assert c.get("/api/v1/ready").json()["worker"]["alive"] is True
        supervisor_procs = [p for p in __import__("gc").get_objects()
                            if type(p).__name__ == "EmbeddedWorker"]
        proc = supervisor_procs[-1].proc
        assert proc.poll() is None
    assert proc.poll() is not None  # terminated on API shutdown: no orphaned worker
