from tests.api.conftest import create_job, upload_ok


def test_create_job_returns_202_promptly(client, train_video):
    vid = upload_ok(client, train_video)
    r = create_job(client, vid, {"target_fps": 10, "counting_mode": "registry"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["job_id"].startswith("job_") and body["video_id"] == vid
    assert body["status"] == "queued" and body["created_at"].endswith("Z")
    assert body["status_url"] == f"/api/v1/jobs/{body['job_id']}"
    assert r.headers["location"] == body["status_url"]

    status = client.get(body["status_url"]).json()
    assert status["status"] == "queued" and status["progress_percent"] == 0
    assert status["options"] == {"target_fps": 10.0, "counting_mode": "registry"}
    assert status["links"]["results"] is None and status["error"] is None


def test_unknown_video_is_404(client):
    r = create_job(client, "vid_" + "a" * 32)
    assert r.status_code == 404 and r.json()["error"]["code"] == "VIDEO_NOT_FOUND"


def test_invalid_requests_are_422(client, train_video):
    vid = upload_ok(client, train_video)
    cases = [
        {"video_id": vid, "options": {"target_fps": 500}},
        {"video_id": vid, "options": {"model_path": "C:/evil.pt"}},  # paths/models are not options
        {"video_id": vid, "options": {"counting_mode": "magic"}},
        {"video_id": "../../etc/passwd"},
        {"video_id": vid, "output_dir": "/tmp"},
        {},
    ]
    for body in cases:
        r = client.post("/api/v1/jobs", json=body)
        assert r.status_code == 422, body
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_duplicate_active_job_is_409_with_existing_id(client, train_video):
    vid = upload_ok(client, train_video)
    first = create_job(client, vid).json()
    r = create_job(client, vid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "JOB_ALREADY_ACTIVE"
    assert r.json()["error"]["details"]["job_id"] == first["job_id"]
    # Different options are a different job.
    assert create_job(client, vid, {"target_fps": 15}).status_code == 202


def test_idempotency_key_replays_the_same_job(client, train_video):
    vid = upload_ok(client, train_video)
    h = {"Idempotency-Key": "click-123"}
    a = create_job(client, vid, headers=h)
    b = create_job(client, vid, headers=h)
    assert a.status_code == b.status_code == 202
    assert a.json()["job_id"] == b.json()["job_id"]
    assert b.headers.get("idempotent-replayed") == "true"
    other = upload_ok(client, train_video)
    r = create_job(client, other, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_unknown_and_malformed_job_ids_are_404(client):
    for jid in ["job_" + "0" * 32, "nope", "job_../x"]:
        r = client.get(f"/api/v1/jobs/{jid}")
        assert r.status_code == 404 and r.json()["error"]["code"] in ("JOB_NOT_FOUND", "NOT_FOUND")
    assert client.get("/api/v1/jobs/" + "job_" + "0" * 32 + "/results").status_code == 404


def test_list_jobs_newest_first_with_filters_and_pagination(client, train_video):
    vid = upload_ok(client, train_video)
    ids = [create_job(client, vid, {"target_fps": f}).json()["job_id"] for f in (10, 11, 12)]
    client.post(f"/api/v1/jobs/{ids[0]}/cancel")
    page = client.get("/api/v1/jobs", params={"limit": 2}).json()
    assert page["total"] == 3 and page["limit"] == 2
    assert [j["job_id"] for j in page["items"]] == [ids[2], ids[1]]
    page2 = client.get("/api/v1/jobs", params={"limit": 2, "offset": 2}).json()
    assert [j["job_id"] for j in page2["items"]] == [ids[0]]
    cancelled = client.get("/api/v1/jobs", params={"status": "cancelled"}).json()
    assert [j["job_id"] for j in cancelled["items"]] == [ids[0]]
    assert client.get("/api/v1/jobs", params={"created_after": "2999-01-01T00:00:00Z"}).json()["total"] == 0
    assert client.get("/api/v1/jobs", params={"status": "bogus"}).status_code == 422


def test_cancel_queued_job_immediately(client, train_video):
    vid = upload_ok(client, train_video)
    jid = create_job(client, vid).json()["job_id"]
    r = client.post(f"/api/v1/jobs/{jid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "cancelled" and job["error"]["code"] == "JOB_CANCELLED"
    again = client.post(f"/api/v1/jobs/{jid}/cancel")
    assert again.status_code == 409 and again.json()["error"]["code"] == "JOB_NOT_CANCELLABLE"
    # A cancelled job no longer blocks an identical new job.
    assert create_job(client, vid).status_code == 202


def test_results_and_downloads_before_completion_are_409(client, train_video):
    vid = upload_ok(client, train_video)
    jid = create_job(client, vid).json()["job_id"]
    for path in ["results", "video", "exports/json", "exports/csv"]:
        r = client.get(f"/api/v1/jobs/{jid}/{path}")
        assert r.status_code == 409 and r.json()["error"]["code"] == "JOB_NOT_COMPLETED", path
    assert client.get(f"/api/v1/jobs/{jid}/exports/xml").status_code == 422
