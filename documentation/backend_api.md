# Backend API — Freight Train Intelligence Platform

The API exposes the existing video pipeline (`backend/app/pipeline`) to a frontend: upload a
video, start an asynchronous processing job, poll its progress, then fetch counts, the wagon
sequence, the annotated video and JSON/CSV exports. The pipeline itself is unchanged apart from
two additive hooks (cooperative cancellation and per-frame rendering progress); the CLI
(`python -m app.cli process ...`) still works exactly as before.

> **Security:** there is no authentication. The API binds to `127.0.0.1` by default and is meant
> for a trusted local/demo environment. Do not expose it publicly without adding access control.

---

## 1. Quick start

```bash
# from the repository root, with the Python 3.11 venv
.venv\Scripts\activate
pip install -r backend/requirements-dev.txt        # torch must already be installed (see README)
cd backend
copy .env.example .env                              # optional; defaults work as-is
python -m app.serve                                 # API + background worker, one command
```

* API: `http://127.0.0.1:8000/api/v1` — Swagger UI: `http://127.0.0.1:8000/docs`, ReDoc: `/redoc`,
  OpenAPI JSON: `/api/v1/openapi.json`
* The database and storage folders are created automatically on startup
  (`python -m app.cli init-db` does the same explicitly).
* Stop with `Ctrl+C` (the embedded worker is stopped too).

Separate processes (e.g. to run the worker on its own console, or several workers):

```bash
set FTIP_START_EMBEDDED_WORKER=false
python -m app.serve            # terminal 1: API only
python -m app.workers          # terminal 2: worker  (python -m app.workers --once: one job, then exit)
```

## 2. Architecture

```
Frontend ──HTTP──► FastAPI (app/main.py, routes → services)        SQLite (WAL)  storage/app.db
                     │  no inference in the API process              videos · jobs · artifacts ·
                     │                                               worker_heartbeats
                     ├── LocalFileStorage (storage/)  ◄─────────────────────┐
                     └── EmbeddedWorker: starts + supervises ─► python -m app.workers
                                                                   claim job (atomic) → PipelineRunner
                                                                   → app.pipeline.process_video(...)
```

| Component | File(s) | Responsibility |
|---|---|---|
| App factory, middleware | `app/main.py` | Routers, CORS, request IDs, upload size limit, embedded worker supervision |
| One-command launcher | `app/serve.py` | `uvicorn` with settings from `FTIP_*` |
| Settings | `app/core/settings.py` | `FTIP_*` env vars / `backend/.env` |
| Routes | `app/api/routes/{health,videos,jobs}.py` | Thin HTTP handlers |
| Errors | `app/api/errors.py` | Error codes → HTTP status, consistent error body |
| Schemas | `app/schemas/*.py` | Pydantic request/response models (separate from pipeline models) |
| Services | `app/services/*.py` | Upload validation, job creation/cancel, result sanitising, links |
| Repositories | `app/repositories/*.py` | All SQL; job state machine; swap-in point for PostgreSQL |
| Storage | `app/storage/file_storage.py` | Safe storage keys, streaming writes, disk checks |
| Worker | `app/workers/video_worker.py`, `__main__.py` | Claim loop, heartbeats, recovery, cancellation |
| Pipeline adapter | `app/workers/pipeline_runner.py` | Job options → `PipelineConfig`, cached detector, progress + error mapping |

**Why this design.** One machine and one GPU: a SQLite-backed queue polled by a separate worker
process gives persistence, crash recovery and no extra infrastructure (no Redis/Celery). The
worker runs one job at a time (the pipeline's ByteTrack uses a process-global track-ID counter, and
a 4 GB GPU should not run several inference jobs). Job claims are atomic (`BEGIN IMMEDIATE` +
conditional `UPDATE`), so several worker processes could run safely. Replacing the queue later
(Celery, RQ, …) only touches `app/workers`; replacing SQLite only touches `app/repositories`.

## 3. Job lifecycle

```
POST /jobs ─► queued ──worker claims──► running ──► completed
                │                          ├──────► failed      (error.code explains why)
                │                          ├──────► cancelled   (cooperative cancel)
                │                          └─ worker died ─► queued again (once), then failed
                └── POST /cancel ─► cancelled
```

* **Progress** comes from real pipeline events: `loading_model` 2 %, `detecting_and_tracking`
  5–85 % (frames processed / estimated sampled frames), `resolving` 86 %, `rendering` 88–99 %
  (frames rendered), `completed` 100 %. If the frame total is unknown, `progress_percent` stays
  at its last value / `null` and only `stage` + `message` change. It never decreases.
* **Cancellation:** a queued job is cancelled immediately; a running job is flagged and the
  pipeline stops at the next frame check (measured: ~0.7 s on a real GPU job).
* **Worker crash / restart:** the worker refreshes a heartbeat every 5 s. A running job is treated
  as interrupted when its worker misses 3 heartbeats (~15 s) or the job has no heartbeat for
  `FTIP_STALE_JOB_SECONDS` (60 s). It is re-queued once (`FTIP_MAX_ATTEMPTS=2`); a second
  interruption fails it with `WORKER_INTERRUPTED`. Each attempt starts with a fresh output folder.
  Measured: after hard-killing the server mid-job and restarting, the job was re-queued and
  re-claimed 12 s after the restart and completed.
* **Duplicates:** an identical job (same video + same options) that is still queued/running is
  rejected with `409 JOB_ALREADY_ACTIVE` (enforced by a partial unique index). Clients can also send
  an `Idempotency-Key` header: repeating a request with the same key returns the original job.
* Results, job records and files persist across API/worker restarts.

## 4. Endpoints (`/api/v1`)

| Method & path | Success | Notes |
|---|---|---|
| `GET /health` | 200 `{status, version}` | Process is responding |
| `GET /ready` | 200 / 503 | Checks database, storage write, free disk, model file; `worker` (alive/busy) is informational |
| `POST /videos` | 201 `Video` | multipart field `file`; `.mp4 .mov .avi .mkv`; ≤ 2 GiB; decoded to validate |
| `GET /videos/{video_id}` | 200 `Video` | |
| `DELETE /videos/{video_id}` | 200 `Video` (`status: deleted`) | 409 `VIDEO_IN_USE` while a queued/running job uses it; job results are kept |
| `POST /jobs` | **202** `JobCreated` + `Location` | Body `{video_id, options?}`; header `Idempotency-Key` optional |
| `GET /jobs` | 200 `{items, total, limit, offset}` | Newest first; `status`, `video_id`, `created_after`, `created_before`, `limit` (≤100), `offset` |
| `GET /jobs/{job_id}` | 200 `Job` | Status, stage, progress, timestamps, error, summary, links |
| `POST /jobs/{job_id}/cancel` | 200 `{status, cancel_requested, message}` | 409 `JOB_NOT_CANCELLABLE` when finished |
| `GET /jobs/{job_id}/results` | 200 | `{summary, result, links}`; `result` = pipeline `result.json` (schema 1.0) with paths reduced to file names |
| `GET /jobs/{job_id}/video` | 200/206 `video/mp4` | HTTP Range supported (seeking); `?download=true` for attachment |
| `GET /jobs/{job_id}/exports/json` | 200 `application/json` | Same document as `results.result` |
| `GET /jobs/{job_id}/exports/csv` | 200 `text/csv` | `wagons.csv` (sequence table) |
| `GET /jobs/{job_id}/exports/tracks_csv` | 200 `text/csv` | `tracks.csv` (per-frame observations) |

Results/video/exports return `409 JOB_NOT_COMPLETED` while queued/running (details include
`status` and `progress_percent`), `409 JOB_FAILED` / `JOB_CANCELLED` for finished-without-results
jobs, and `404 ARTIFACT_NOT_AVAILABLE` if an output was not produced (e.g. `write_video: false`) or
is missing on disk.

### Job options (all optional, unknown keys rejected with 422)

| Option | Range | Pipeline setting |
|---|---|---|
| `target_fps` | 1–60 | `sampling.target_fps` |
| `confidence_threshold` | 0.05–0.95 | `detector.confidence_threshold` |
| `counting_mode` | `registry` \| `line` | `counting.mode` |
| `line_position` | 0.05–0.95 | `counting.line_position` |
| `travel_axis` | `auto` \| `x` \| `y` | `counting.travel_axis` |
| `write_video` | bool | `output.write_video` |

The model and every filesystem path are fixed server-side (`backend/configs/default.yaml`,
weights in `backend/models/`); clients cannot select them.

### Key response fields

`Job.result_summary` (completed jobs): `total_wagons` (excludes `excluded_classes`, i.e.
locomotives), `total_rolling_stock`, `type_counts`, `not_counted`, `sequence_completeness`,
`uncertain_sequence_items`, `warnings`, `annotated_video_codec`, `browser_playable_video`.

All timestamps are UTC ISO-8601 with a `Z` suffix. Links are API-relative (`/api/v1/...`) unless
`FTIP_PUBLIC_BASE_URL` is set.

## 5. Errors

```json
{"error": {"code": "JOB_NOT_FOUND", "message": "Job 'job_…' does not exist", "details": {}},
 "request_id": "3eb03e52ccc64bc4820940deb6da9491"}
```

| HTTP | Codes |
|---|---|
| 400 | `EMPTY_UPLOAD`, `BAD_REQUEST` |
| 404 | `VIDEO_NOT_FOUND`, `JOB_NOT_FOUND`, `ARTIFACT_NOT_AVAILABLE`, `NOT_FOUND` |
| 409 | `VIDEO_NOT_AVAILABLE`, `VIDEO_IN_USE`, `JOB_ALREADY_ACTIVE`, `IDEMPOTENCY_KEY_REUSED`, `JOB_NOT_COMPLETED`, `JOB_FAILED`, `JOB_CANCELLED`, `JOB_NOT_CANCELLABLE` |
| 413 | `UPLOAD_TOO_LARGE` |
| 415 | `UNSUPPORTED_FILE_TYPE` (extension), `UNSUPPORTED_VIDEO` (cannot be decoded) |
| 422 | `VALIDATION_ERROR` (`details.errors` lists fields) |
| 500 | `INTERNAL_ERROR` |
| 503 | `DATABASE_UNAVAILABLE`, readiness failures |
| 507 | `INSUFFICIENT_STORAGE` |

Failed jobs carry `error.code` from: `INVALID_VIDEO`, `MODEL_UNAVAILABLE`, `INFERENCE_FAILED`,
`TRACKING_FAILED`, `OUTPUT_WRITE_FAILED`, `INSUFFICIENT_STORAGE`, `INVALID_CONFIGURATION`,
`VIDEO_NOT_AVAILABLE`, `WORKER_INTERRUPTED`, `INTERNAL_ERROR` (cancelled jobs: `JOB_CANCELLED`).
Messages never contain stack traces or server paths; the full exception is stored in
`jobs.internal_error` and the logs. Every response carries `X-Request-ID` for correlating logs.

## 6. Example workflow (curl)

```bash
API=http://127.0.0.1:8000/api/v1

# 1. upload
curl -F "file=@D:/videos/YT-073.mp4" $API/videos
#  -> 201 {"video_id":"vid_d711…","original_filename":"YT-073.mp4","duration_seconds":49.35,"fps":60.0,...}

# 2. start processing (returns immediately)
curl -X POST $API/jobs -H "Content-Type: application/json" -H "Idempotency-Key: my-click-1" \
     -d "{\"video_id\":\"vid_d711…\",\"options\":{\"target_fps\":30}}"
#  -> 202 {"job_id":"job_5f27…","status":"queued","status_url":"/api/v1/jobs/job_5f27…","poll_interval_seconds":2.0}

# 3. poll every ~2 s until status is completed / failed / cancelled
curl $API/jobs/job_5f27…
#  -> {"status":"running","stage":"detecting_and_tracking","progress_percent":45.6,
#      "message":"Detecting and tracking wagons (frame 751/1480)", ...}

# 4. results and files
curl $API/jobs/job_5f27…/results                    # counts, sequence, wagon records, flags
curl -OJ $API/jobs/job_5f27…/exports/csv            # job_5f27…_wagons.csv
curl -OJ $API/jobs/job_5f27…/exports/json           # job_5f27…_result.json
curl -o annotated.mp4 $API/jobs/job_5f27…/video     # or use the URL directly in <video src=...>

# optional
curl -X POST $API/jobs/job_5f27…/cancel
curl "$API/jobs?status=completed&limit=10"
```

Measured on this machine (RTX 2050, YT-073: 49 s, 1280×720, 60 fps): upload + validation < 1 s,
job finished ~50 s after creation; result 60 wagons (+2 locomotives), H.264 output video.

### Frontend notes

* Polling: use `poll_interval_seconds` (2 s); stop when `status` ∈ {completed, failed, cancelled}.
* Show `stage` + `message`; render a progress bar only when `progress_percent` is not null.
* `<video src="{API}{links.annotated_video}">` works directly (Range requests supported). If
  `result_summary.browser_playable_video` is false, the server's OpenCV build fell back to the
  `mp4v` codec: offer the download link instead.
* Use `links.*` from responses rather than building URLs.
* CORS: allowed origins come from `FTIP_CORS_ORIGINS` (default: the Vite frontend at
  `http://localhost:5173` / `http://127.0.0.1:5173`, plus `http://localhost:3000`).
  Exposed headers include `X-Request-ID`, `Location`, `Content-Disposition`, `Content-Range`.
* Uncertainty: `result.wagons[].flags`, `result.sequence[].uncertain`, `result.warnings` and
  `result.unresolved_identities` should be shown, not hidden (see `documentation/output_schema.md`).

## 7. Database schema (SQLite, `storage/app.db`, WAL mode, foreign keys on)

| Table | Key columns |
|---|---|
| `videos` | `video_id` PK, `original_filename`, `storage_key` UNIQUE, `extension`, `content_type`, `size_bytes`, `status` (`ready`/`deleted`), `duration_seconds`, `fps`, `width`, `height`, `frame_count`, `codec`, `uploaded_at`, `deleted_at` |
| `jobs` | `job_id` PK, `video_id` FK, `status` (CHECK), `stage`, `progress_percent` (0–100), `message`, `options_json`, `options_hash`, `idempotency_key` UNIQUE, `cancel_requested`, `attempts`, `error_code`, `error_message`, `internal_error` (never returned), `config_snapshot_json`, `model_json`, `summary_json`, `worker_id`, `created_at`, `started_at`, `finished_at`, `heartbeat_at`, `updated_at`; partial UNIQUE (`video_id`, `options_hash`) WHERE status IN (queued, running) |
| `artifacts` | PK (`job_id`, `kind`), `storage_key`, `size_bytes`, `media_type`, `created_at` — kinds: `annotated_video`, `result_json`, `result_public_json`, `wagons_csv`, `tracks_csv`, `summary`, `log` |
| `worker_heartbeats` | `worker_id` PK, `hostname`, `pid`, `started_at`, `last_seen`, `current_job_id` |
| `schema_version` | `version` (currently 1) |

Large files are never stored in the database.

## 8. Storage layout (`FTIP_STORAGE_ROOT`, default `backend/storage/`, git-ignored)

```
storage/
├── app.db                         SQLite database (+ -wal/-shm)
├── uploads/{video_id}{ext}        uploaded videos (server-generated names)
├── jobs/{job_id}/outputs/         annotated.mp4, result.json, result.public.json, wagons.csv,
│                                  tracks.csv, summary.txt, run.log
└── temporary/                     in-progress uploads; files older than 24 h removed on startup
```

Only storage keys built from server-generated IDs are used; keys that could escape the root are
rejected. Model weights stay in `backend/models/`. **Retention:** nothing is deleted
automatically; `DELETE /videos/{id}` removes an upload. Job outputs are kept until removed manually.

## 9. Configuration

All settings are `FTIP_*` environment variables or entries in `backend/.env` — see
`backend/.env.example` for the full list and defaults (host/port, CORS origins, storage root,
database path, 2 GiB upload limit, allowed extensions, minimum free disk, worker polling,
heartbeat/stale timeouts, retry attempts, embedded worker on/off). Pipeline and model settings stay
in `backend/configs/default.yaml` (`FTIP_PIPELINE_CONFIG` to use another file).

## 10. Testing

```bash
cd backend
python -m pytest                 # pipeline + API + worker tests (no GPU needed)
python -m pytest tests/api       # API/worker tests only
```

API/worker tests run the **real pipeline** (`process_video`, ByteTrack, resolution, rendering,
exports) on a synthetic video with a scripted detector, so they need no GPU. Model inference is
covered by `tests/integration/test_model_smoke.py`, and a real video by
`tests/integration/test_real_video.py` (`WAGON_SAMPLE_VIDEO=...`).

## 11. Deployment considerations & limitations

* **Single machine by design.** SQLite + one worker process. For several machines/GPUs: move to
  PostgreSQL (new repository classes) and a real queue (Celery/RQ) behind `app/workers`.
* **No authentication/authorization.** Add it (and per-user job ownership) before any public use;
  then also set `allow_credentials` in CORS consistently.
* **Upload buffering:** Starlette spools a multipart upload to a system temporary file before the
  handler copies it into `storage/temporary/`, so a large upload is briefly written twice.
  Oversized uploads are rejected early (Content-Length) or while streaming.
* **Video codec:** browser playback needs H.264 (`avc1`); OpenCV builds without an H.264 encoder fall
  back to `mp4v` (reported as `browser_playable_video: false`). Transcoding with ffmpeg is a future
  improvement.
* **Cancellation granularity:** checked between frames; model loading and the short resolution
  step cannot be interrupted midway.
* **Shutdown during a job:** stopping the server terminates the worker; the job is recovered and
  re-queued once on the next start.
* Only one job runs at a time per worker; queued jobs wait in order of creation.
