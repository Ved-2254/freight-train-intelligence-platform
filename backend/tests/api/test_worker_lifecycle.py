"""Job lifecycle through the worker. Uses the real pipeline with a scripted detector."""

import csv
import io
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import InferenceError, ModelLoadError
from app.core.ids import to_utc_string
from app.repositories.database import Database
from app.repositories.job_repository import JobRepository
from app.storage.file_storage import LocalFileStorage
from app.workers.video_worker import VideoWorker
from tests.api.conftest import create_job, scripted_runner, upload_ok


def _run_job(client, worker, video, options=None):
    vid = upload_ok(client, video)
    jid = create_job(client, vid, options).json()["job_id"]
    assert worker.run_once() is True
    return vid, jid


def test_successful_lifecycle_exposes_real_pipeline_results(client, worker, train_video, settings):
    vid, jid = _run_job(client, worker, train_video)
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "completed", job
    assert job["progress_percent"] == 100 and job["stage"] == "completed" and job["attempts"] == 1
    assert job["started_at"] and job["finished_at"]
    s = job["result_summary"]
    # Synthetic train: Locomotive, BOXN, BCN -> 3 rolling stock, 2 wagons (locomotive excluded).
    assert s["total_rolling_stock"] == 3 and s["total_wagons"] == 2
    assert s["excluded_classes"] == ["Locomotive"]
    for key in ("results", "annotated_video", "exports"):
        assert job["links"][key]

    res = client.get(job["links"]["results"])
    assert res.status_code == 200
    body = res.json()
    assert body["result"]["schema_version"] == "1.0"
    assert body["result"]["counts"]["wagons_only_total"] == 2
    assert [s["class_name"] for s in body["result"]["sequence"]] == ["Locomotive", "BOXN", "BCN"]
    assert body["result"]["input"]["path"] == "train.mp4"  # original name, not a server path
    text = res.text
    assert str(settings.storage_root) not in text and ":\\\\" not in text
    assert body["result"]["model"]["model_file"] == "synthetic"


def test_exports_and_video_downloads(client, worker, train_video):
    _, jid = _run_job(client, worker, train_video)

    j = client.get(f"/api/v1/jobs/{jid}/exports/json")
    assert j.status_code == 200 and j.headers["content-type"].startswith("application/json")
    assert f'filename="{jid}_result.json"' in j.headers["content-disposition"]
    assert json.loads(j.content)["run_id"] == jid

    c = client.get(f"/api/v1/jobs/{jid}/exports/csv")
    assert c.status_code == 200 and c.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(c.text)))
    assert [r["class_name"] for r in rows if r["sequence_position"]] == ["Locomotive", "BOXN", "BCN"]

    t = client.get(f"/api/v1/jobs/{jid}/exports/tracks_csv")
    assert t.status_code == 200 and t.text.startswith("wagon_uid,track_id")

    v = client.get(f"/api/v1/jobs/{jid}/video")
    assert v.status_code == 200 and v.headers["content-type"] == "video/mp4"
    assert v.headers["accept-ranges"] == "bytes" and v.headers["content-disposition"].startswith("inline")
    size = len(v.content)
    part = client.get(f"/api/v1/jobs/{jid}/video", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert part.headers["content-range"] == f"bytes 0-99/{size}"
    dl = client.get(f"/api/v1/jobs/{jid}/video", params={"download": "true"})
    assert dl.headers["content-disposition"].startswith("attachment")


def test_job_without_video_has_no_video_artifact(client, worker, train_video):
    _, jid = _run_job(client, worker, train_video, {"write_video": False})
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "completed" and job["links"]["annotated_video"] is None
    r = client.get(f"/api/v1/jobs/{jid}/video")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ARTIFACT_NOT_AVAILABLE"


def test_missing_artifact_file_is_404(client, worker, train_video, settings):
    _, jid = _run_job(client, worker, train_video)
    (settings.storage_root / "jobs" / jid / "outputs" / "wagons.csv").unlink()
    r = client.get(f"/api/v1/jobs/{jid}/exports/csv")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ARTIFACT_NOT_AVAILABLE"


class _FailingRunner:
    def __init__(self, exc):
        self.exc = exc

    def run(self, ctx):
        ctx.on_progress("detecting_and_tracking", 10.0, "working")
        raise self.exc


@pytest.mark.parametrize("exc, code", [
    (InferenceError("CUDA error at D:\\secret\\path\\model.pt"), "INFERENCE_FAILED"),
    (ModelLoadError("Model weights not found: C:\\x\\best.pt"), "MODEL_UNAVAILABLE"),
    (RuntimeError("boom"), "INTERNAL_ERROR"),
])
def test_pipeline_failures_are_sanitised(client, worker, train_video, exc, code):
    worker.runner = _FailingRunner(exc)
    _, jid = _run_job(client, worker, train_video)
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "failed" and job["error"]["code"] == code
    assert "secret" not in job["error"]["message"] and ":\\" not in str(job)
    r = client.get(f"/api/v1/jobs/{jid}/results")
    assert r.status_code == 409 and r.json()["error"]["code"] == "JOB_FAILED"
    # The internal diagnostic is stored server-side only.
    assert JobRepository(worker.db).get(jid).internal_error


def test_failure_does_not_stop_the_worker(client, worker, train_video):
    worker.runner = _FailingRunner(RuntimeError("first job breaks"))
    _, first = _run_job(client, worker, train_video)
    worker.runner = scripted_runner(worker.settings)
    _, second = _run_job(client, worker, train_video)
    assert client.get(f"/api/v1/jobs/{first}").json()["status"] == "failed"
    assert client.get(f"/api/v1/jobs/{second}").json()["status"] == "completed"


def test_cancel_running_job_stops_pipeline(client, worker, train_video):
    vid = upload_ok(client, train_video)
    jid = create_job(client, vid).json()["job_id"]
    real_checker = worker._cancel_checker

    def checker_that_requests_cancel(job_id):
        check = real_checker(job_id)
        calls = {"n": 0}

        def wrapped():
            calls["n"] += 1
            if calls["n"] == 5:  # user presses "cancel" while frames are being processed
                r = client.post(f"/api/v1/jobs/{jid}/cancel")
                assert r.status_code == 200 and r.json()["status"] == "running"
            return check()

        return wrapped

    worker._cancel_checker = checker_that_requests_cancel
    assert worker.run_once()
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "cancelled" and job["error"]["code"] == "JOB_CANCELLED"
    assert job["cancel_requested"] is True


def test_progress_is_persisted_and_monotonic(client, worker, train_video):
    vid = upload_ok(client, train_video)
    jid = create_job(client, vid).json()["job_id"]
    seen = []
    original = worker.jobs.update_progress

    def spy(job_id, stage, percent, message):
        seen.append((stage, percent))
        db_job = original(job_id, stage, percent, message)
        return db_job

    worker.jobs.update_progress = spy
    worker.run_once()
    stages = [s for s, _ in seen]
    assert stages[0] == "loading_model"
    assert "detecting_and_tracking" in stages and "rendering" in stages
    pcts = [p for _, p in seen if p is not None]
    assert pcts == sorted(pcts) and pcts[-1] <= 99.0


def test_interrupted_job_is_requeued_once_then_failed(client, worker, train_video, settings):
    vid = upload_ok(client, train_video)
    jid = create_job(client, vid).json()["job_id"]
    repo = JobRepository(worker.db)
    old = to_utc_string(datetime.now(timezone.utc) - timedelta(seconds=settings.stale_job_seconds * 2))

    def simulate_crash():
        claimed = repo.claim_next("crashed-worker")
        assert claimed.job_id == jid
        with worker.db.connect() as conn:
            conn.execute("UPDATE jobs SET heartbeat_at = ? WHERE job_id = ?", (old, jid))

    simulate_crash()
    assert worker.recover_stale_jobs() == [(jid, "queued")]
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "queued" and job["attempts"] == 1

    simulate_crash()  # second attempt also dies
    assert worker.recover_stale_jobs() == [(jid, "failed")]
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "WORKER_INTERRUPTED" and job["attempts"] == 2


def test_requeued_job_completes_on_restart(client, worker, train_video, settings):
    vid = upload_ok(client, train_video)
    jid = create_job(client, vid).json()["job_id"]
    repo = JobRepository(worker.db)
    repo.claim_next("crashed-worker")
    old = to_utc_string(datetime.now(timezone.utc) - timedelta(hours=1))
    with worker.db.connect() as conn:
        conn.execute("UPDATE jobs SET heartbeat_at = ? WHERE job_id = ?", (old, jid))
    # "Restart": a new worker initialises (recovers) and processes the re-queued job.
    fresh = VideoWorker(settings, Database(settings.db_path), LocalFileStorage(settings.storage_root),
                        scripted_runner(settings), worker_id="restarted")
    fresh.initialize()
    assert fresh.run_once()
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "completed" and job["attempts"] == 2


def test_concurrent_workers_never_claim_the_same_job(client, settings, train_video):
    vid = upload_ok(client, train_video)
    ids = {create_job(client, vid, {"target_fps": f}).json()["job_id"] for f in (5, 6, 7, 8)}
    repo = JobRepository(Database(settings.db_path))
    claimed, lock = [], threading.Lock()

    def claim_all(name):
        while (job := repo.claim_next(name)) is not None:
            with lock:
                claimed.append(job.job_id)

    threads = [threading.Thread(target=claim_all, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(claimed) == sorted(ids)  # each job claimed exactly once


def test_job_for_deleted_video_fails_cleanly(client, worker, train_video, settings):
    vid = upload_ok(client, train_video)
    jid = create_job(client, vid).json()["job_id"]
    # Simulate the file disappearing behind the API's back.
    for p in (settings.storage_root / "uploads").iterdir():
        p.unlink()
    worker.run_once()
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "VIDEO_NOT_AVAILABLE"


def test_completed_jobs_survive_api_restart(tmp_path, train_video):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.api.conftest import make_settings

    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, start_worker=False)) as c1:
        vid = upload_ok(c1, train_video)
        jid = create_job(c1, vid).json()["job_id"]
        w = VideoWorker(settings, Database(settings.db_path), LocalFileStorage(settings.storage_root),
                        scripted_runner(settings), worker_id="w")
        w.initialize()
        w.run_once()
    with TestClient(create_app(settings, start_worker=False)) as c2:  # new process-equivalent
        assert c2.get(f"/api/v1/jobs/{jid}").json()["status"] == "completed"
        assert c2.get(f"/api/v1/jobs/{jid}/results").status_code == 200
        assert c2.get(f"/api/v1/jobs/{jid}/exports/csv").status_code == 200


def test_job_of_dead_worker_is_recovered_before_stale_timeout(client, worker, train_video, settings):
    from app.repositories.job_repository import WorkerRepository

    vid = upload_ok(client, train_video)
    jid = create_job(client, vid).json()["job_id"]
    repo = JobRepository(worker.db)
    repo.claim_next("dead-worker")  # job heartbeat is fresh...
    old = to_utc_string(datetime.now(timezone.utc) - timedelta(seconds=settings.heartbeat_seconds * 10))
    with worker.db.connect() as conn:  # ...but its worker stopped beating long ago
        conn.execute("INSERT INTO worker_heartbeats (worker_id, started_at, last_seen) VALUES (?, ?, ?)",
                     ("dead-worker", old, old))
    assert worker.recover_stale_jobs() == [(jid, "queued")]


def test_job_of_live_worker_is_not_recovered(client, worker, train_video):
    from app.core.ids import utc_now
    from app.repositories.job_repository import WorkerRepository

    vid = upload_ok(client, train_video)
    create_job(client, vid)
    JobRepository(worker.db).claim_next("live-worker")
    WorkerRepository(worker.db).beat("live-worker", "h", 1, utc_now(), None)
    assert worker.recover_stale_jobs() == []
