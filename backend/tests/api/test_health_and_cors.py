from fastapi.testclient import TestClient

from app.main import create_app
from tests.api.conftest import make_settings


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.headers["x-request-id"]


def test_ready_reports_checks_without_paths(client):
    r = client.get("/api/v1/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert all(c["ok"] for c in body["checks"].values())
    assert body["checks"]["model_file"]["model_file"] == "best.pt" or body["checks"]["model_file"]["ok"]
    assert ":\\" not in r.text and "/storage" not in r.text
    assert body["worker"]["alive"] is False


def test_ready_is_503_when_database_unavailable(tmp_path):
    settings = make_settings(tmp_path)
    app = create_app(settings, start_worker=False)
    with TestClient(app) as c:
        # Replace the DB path with a directory: connections now fail.
        bad = tmp_path / "not_a_db"
        bad.mkdir()
        app.state.container.db.path = bad
        r = c.get("/api/v1/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["database"]["ok"] is False


def test_ready_is_503_when_model_missing(tmp_path):
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text("detector:\n  model_path: backend/models/does_not_exist.pt\n", encoding="utf-8")
    with TestClient(create_app(make_settings(tmp_path, pipeline_config=cfg), start_worker=False)) as c:
        r = c.get("/api/v1/ready")
    assert r.status_code == 503 and r.json()["checks"]["model_file"]["ok"] is False


def test_request_id_is_echoed(client):
    r = client.get("/api/v1/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"


def test_cors_allows_configured_origin_only(client):
    ok = client.options("/api/v1/jobs", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,idempotency-key"})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    bad = client.options("/api/v1/jobs", headers={
        "Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers
    simple = client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})
    assert simple.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "x-request-id" in simple.headers["access-control-expose-headers"].lower()


def test_unknown_route_uses_error_format(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND" and r.json()["request_id"]


def test_openapi_documents_all_endpoints(client):
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    for p in ["/api/v1/health", "/api/v1/ready", "/api/v1/videos", "/api/v1/videos/{video_id}", "/api/v1/jobs",
              "/api/v1/jobs/{job_id}", "/api/v1/jobs/{job_id}/cancel", "/api/v1/jobs/{job_id}/results",
              "/api/v1/jobs/{job_id}/video", "/api/v1/jobs/{job_id}/exports/{fmt}"]:
        assert p in paths, p
