# Future Improvements (post-demo backlog)

Collected during the pipeline and backend API work (October 2026). Nothing here blocks the demo.
Priority: **P1** = do soon after the demo, **P2** = before wider use, **P3** = later / when scaling.

## 1. Storage and disk usage

| # | Improvement | Why | Priority |
|---|---|---|---|
| 1.1 | `DELETE /api/v1/jobs/{job_id}`: remove a finished job's output folder and artifact rows (refuse while queued/running) | Today job outputs can only be removed by hand from `backend/storage/jobs/<job_id>/` | P1 |
| 1.2 | Retention policy: optional automatic cleanup of job outputs and unused uploads older than N days (setting, e.g. `FTIP_RETENTION_DAYS`, run at startup and periodically) | Outputs are kept forever; the annotated video alone was 157 MB for a 65 MB input (YT-073) | P1 |
| 1.3 | Clean up partial outputs of failed/cancelled jobs (or keep only `run.log`) | Leaves small leftover folders (~10 KB each) | P2 |
| 1.4 | Smaller annotated video: configurable output resolution/bitrate (e.g. 720p max) | Output is written at source resolution and is larger than the input | P2 |
| 1.5 | Disk-usage figures in `/ready` or a small admin endpoint (uploads / outputs size) | Visibility before the 1 GB free-space guard starts rejecting work | P3 |
| 1.6 | Remove the duplicate model file `backend/models/best.pt.zip` once teammates use `best.pt` (byte-identical copy, 19 MB) | Repository size / confusion | P2 |

## 2. Uploads

| # | Improvement | Why | Priority |
|---|---|---|---|
| 2.1 | Stream the multipart body straight into `storage/temporary/` (python-multipart streaming parser) | Starlette first spools the upload to the system temp folder, so a large upload is written twice | P2 |
| 2.2 | Resumable / chunked uploads for very large files | 2 GB uploads over a slow connection fail as a whole if interrupted | P3 |
| 2.3 | Optional maximum video duration / resolution limits | Bound processing time per job | P3 |

## 3. Video output and playback

| # | Improvement | Why | Priority |
|---|---|---|---|
| 3.1 | Transcode the annotated video to H.264 with ffmpeg when OpenCV falls back to `mp4v` | Browsers cannot play `mp4v`; works on the dev machine (OpenCV has H.264) but not guaranteed elsewhere | P2 |
| 3.2 | Generate a thumbnail / poster image per job | Nicer job lists in the frontend | P3 |

## 4. Job processing and reliability

| # | Improvement | Why | Priority |
|---|---|---|---|
| 4.1 | Graceful shutdown: let the running job finish (or stop it as "interrupted" cleanly) before the worker exits | Stopping the server mid-job currently kills it; the job restarts from the beginning (re-queued once) | P2 |
| 4.2 | Cancellation during model loading / resolution step | Cancellation is checked between frames only | P3 |
| 4.3 | Priority / fair ordering of queued jobs | Strict first-in-first-out today | P3 |
| 4.4 | Multiple GPUs / machines: PostgreSQL repositories + a real queue (Celery/RQ) behind `app/workers` | Current design is single-machine (SQLite + one worker) by choice | P3 |

## 5. Security

| # | Improvement | Why | Priority |
|---|---|---|---|
| 5.1 | Authentication and per-user ownership of videos/jobs | API has no auth; must stay on localhost until added | P2 (P1 before any public deployment) |
| 5.2 | Rate limiting on uploads and job creation | Prevent accidental or abusive load | P3 |
| 5.3 | CORS with credentials once auth (cookies) exists | Currently `allow_credentials=False` | P2 |

## 6. Detection, counting and evaluation (model / pipeline)

| # | Improvement | Why | Priority |
|---|---|---|---|
| 6.1 | Batch evaluation of every video in `Raw Video/` against `FTIP-SGP.xlsx` (`Total_Wagons_Approx`): table of predicted vs hand count and error | Only YT-073 was compared so far (60 wagons + 2 locomotives = 62 rolling stock vs sheet 62) | P1 |
| 6.2 | Confirm whether the sheet's counts include locomotives (pipeline total now excludes them) | Needed to interpret every comparison | P1 |
| 6.3 | Annotation / training: empty flat wagons were mostly missed in YT-011 | Detector recall issue | P1 |
| 6.4 | Annotation / training: distant objects and parked coaches detected as `Locomotive` | False positives (partly handled by the stationary-object rule) | P2 |
| 6.5 | Annotation guideline: one box per whole container wagon, not per container | Container wagons may be boxed per container → over-count | P2 |
| 6.6 | Receding / approaching perspective views (train moving toward or away from the camera) | Large size change along the track; check resolution thresholds on such footage | P3 |

## 7. Developer experience

| # | Improvement | Why | Priority |
|---|---|---|---|
| 7.1 | Switch tests to `httpx2` when Starlette's TestClient requires it | Deprecation warning (currently filtered in `pytest.ini`) | P3 |
| 7.2 | Docker setup for the backend (CUDA base image) | Easier setup for teammates | P3 |
| 7.3 | CI workflow running `pytest` on push | Catch regressions | P3 |
