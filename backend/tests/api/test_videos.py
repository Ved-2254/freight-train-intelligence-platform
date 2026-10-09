import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.errors import ApiError
from app.main import create_app
from tests.api.conftest import create_job, make_settings, upload, upload_ok


def test_valid_upload_is_stored_with_generated_name(client, settings, train_video):
    r = upload(client, train_video, name="My Train (1).mp4")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["video_id"].startswith("vid_")
    assert body["original_filename"] == "My Train (1).mp4"
    assert body["status"] == "ready" and body["width"] == 640 and body["height"] == 360
    assert body["fps"] == pytest.approx(20.0) and body["frame_count"] > 0
    assert body["size_bytes"] == train_video.stat().st_size
    assert body["links"]["self"] == f"/api/v1/videos/{body['video_id']}"
    stored = list((settings.storage_root / "uploads").iterdir())
    assert [p.name for p in stored] == [f"{body['video_id']}.mp4"]
    assert str(settings.storage_root) not in r.text  # no server paths in responses
    assert client.get(body["links"]["self"]).json()["video_id"] == body["video_id"]


def test_path_traversal_filename_is_metadata_only(client, settings, train_video):
    r = upload(client, train_video, name="..\\..\\windows/../evil.mp4")
    assert r.status_code == 201
    assert r.json()["original_filename"] == "evil.mp4"
    assert not (settings.storage_root.parent / "evil.mp4").exists()
    assert all(p.name.startswith("vid_") for p in (settings.storage_root / "uploads").iterdir())


def test_unsupported_extension_is_415(client):
    r = client.post("/api/v1/videos", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert ".mp4" in r.json()["error"]["details"]["supported_extensions"]


def test_corrupt_video_is_415_and_not_stored(client, settings):
    r = client.post("/api/v1/videos", files={"file": ("fake.mp4", b"not really a video" * 500, "video/mp4")})
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_VIDEO"
    assert list((settings.storage_root / "uploads").iterdir()) == []
    assert list((settings.storage_root / "temporary").iterdir()) == []


def test_empty_upload_is_400(client):
    r = client.post("/api/v1/videos", files={"file": ("empty.mp4", b"", "video/mp4")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "EMPTY_UPLOAD"


def test_missing_file_field_is_422(client):
    r = client.post("/api/v1/videos", data={"x": "1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_oversized_upload_rejected_by_content_length(tmp_path, train_video):
    settings = make_settings(tmp_path, max_upload_bytes=10_000)
    with TestClient(create_app(settings, start_worker=False)) as c:
        big = b"\0" * (2 * 1024 * 1024)
        r = c.post("/api/v1/videos", files={"file": ("big.mp4", big, "video/mp4")})
    assert r.status_code == 413 and r.json()["error"]["code"] == "UPLOAD_TOO_LARGE"
    assert r.json()["error"]["details"]["max_upload_bytes"] == 10_000


def test_oversized_upload_rejected_while_streaming(tmp_path, train_video):
    # File larger than the limit but within the multipart slack: caught by the streaming copy.
    settings = make_settings(tmp_path, max_upload_bytes=10_000)
    with TestClient(create_app(settings, start_worker=False)) as c:
        r = c.post("/api/v1/videos", files={"file": ("big.mp4", b"\0" * 50_000, "video/mp4")})
    assert r.status_code == 413 and r.json()["error"]["code"] == "UPLOAD_TOO_LARGE"
    assert list((settings.storage_root / "temporary").iterdir()) == []


def test_service_enforces_limit_without_content_length(tmp_path):
    settings = make_settings(tmp_path, max_upload_bytes=1000)
    app = create_app(settings, start_worker=False)
    with TestClient(app):
        svc = app.state.container.video_service
        with pytest.raises(ApiError) as exc:
            svc.upload(io.BytesIO(b"\0" * 5000), "x.mp4", "video/mp4", content_length=None)
    assert exc.value.code == "UPLOAD_TOO_LARGE"


def test_insufficient_disk_space_is_507(tmp_path, train_video):
    settings = make_settings(tmp_path, min_free_disk_bytes=10**18)
    with TestClient(create_app(settings, start_worker=False)) as c:
        r = upload(c, train_video)
    assert r.status_code == 507 and r.json()["error"]["code"] == "INSUFFICIENT_STORAGE"


def test_unknown_and_malformed_video_ids_are_404(client):
    assert client.get("/api/v1/videos/vid_" + "0" * 32).status_code == 404
    r = client.get("/api/v1/videos/..%2F..%2Fetc")
    assert r.status_code == 404 and r.json()["error"]["code"] in ("VIDEO_NOT_FOUND", "NOT_FOUND")


def test_delete_video_blocked_while_job_active_then_allowed(client, settings, train_video):
    vid = upload_ok(client, train_video)
    job = create_job(client, vid).json()
    r = client.delete(f"/api/v1/videos/{vid}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "VIDEO_IN_USE"
    client.post(f"/api/v1/jobs/{job['job_id']}/cancel")
    r = client.delete(f"/api/v1/videos/{vid}")
    assert r.status_code == 200 and r.json()["status"] == "deleted"
    assert list((settings.storage_root / "uploads").iterdir()) == []
    r = create_job(client, vid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "VIDEO_NOT_AVAILABLE"
