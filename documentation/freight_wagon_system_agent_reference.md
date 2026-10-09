# Freight Wagon Detection, Tracking, Counting & Sequencing System

## Agentic AI Implementation Reference

**Purpose:** This is the implementation guide for an AI coding agent
building the freight-wagon video analysis system. Follow the
architecture and implementation order below. Build the backend
processing pipeline first, but design it from the beginning to fit the
complete future website architecture.

**Project status:** A temporary YOLO model exists and was trained on a
smaller dataset. It will later be replaced by a model trained on a
substantially larger annotated dataset. Make model replacement
configurable; do not hardcode assumptions that prevent this.

------------------------------------------------------------------------

# 1. Project Goal and System Requirements

Build a system that accepts a freight-train video and produces:

1.  An annotated output video.
2.  The total number of distinct wagons in the video.
3.  Counts grouped by wagon class.
4.  An ordered wagon sequence.
5.  Machine-readable JSON and CSV exports.
6.  Processing status, progress, errors, and metadata for a future
    website.

The video-analysis pipeline should:

1.  Validate and open the input video.
2.  Decode frames and sample at a configurable target FPS, initially 30
    FPS where appropriate.
3.  Run a trained YOLO object-detection model on sampled frames.
4.  Pass detections to ByteTrack for multi-object tracking.
5.  Keep per-track histories and stabilize class predictions across
    observations.
6.  Resolve tracker IDs into distinct physical-wagon records where
    possible.
7.  Count distinct wagons and produce type-wise counts.
8.  Infer wagon order using a documented sequence convention.
9.  Generate annotated video and structured output files.
10. Persist job status and results so the website can retrieve them
    after processing.

## Core design principle

Keep these concepts separate:

-   **Detection:** What objects/classes appear in an individual frame?
-   **Tracking:** Which detections likely belong to the same tracked
    object over time?
-   **Wagon resolution / aggregation:** Which observations and track
    fragments correspond to one physical wagon?
-   **Counting:** How many resolved physical wagons should be counted?
-   **Sequencing:** What is the order of the wagons under a documented
    convention?
-   **Reporting:** How are results saved and exposed to the website?

Do not treat a detection as a wagon, and do not automatically treat each
ByteTrack ID as one unique physical wagon.

------------------------------------------------------------------------

# 2. Complete Website Architecture --- Design This First

The final system will have a web frontend, a backend API, a background
processing worker, metadata persistence, and file storage. The first
implementation can be local and simple, but the boundaries must support
future deployment.

## 2.1 High-level architecture

``` text
User
  |
  v
Website Frontend (Next.js + TypeScript)
  |
  | HTTP API requests
  v
Backend API (FastAPI)
  |                    \
  |                     \-- Job/Result Repository --> Database
  |
  +--> File Storage: input videos, output videos, JSON, CSV
  |
  v
Background Job Queue (initially simple worker process;
later Celery + Redis if needed)
  |
  v
Video Processing Worker
  |
  v
Core Computer Vision Pipeline
  |
  +--> Video Reader / Frame Sampler
  +--> YOLO Detector
  +--> ByteTrack Adapter
  +--> Track Manager
  +--> Wagon Registry / Identity Resolution
  +--> Wagon Counter
  +--> Sequence Builder
  +--> Annotated Video Writer
  +--> Result Builder / Exporter
  |
  v
Persist status, metrics, wagon records, and output file references
  |
  v
Website displays status, counts, class chart, sequence, and video
```

## 2.2 Responsibility boundaries

### Frontend

The website should be responsible for:

-   Uploading a video.
-   Showing upload/validation errors.
-   Starting a processing job.
-   Displaying job status and progress.
-   Displaying the current processing stage.
-   Displaying total wagon count.
-   Displaying class-wise counts and charts.
-   Displaying the ordered wagon sequence.
-   Playing or opening the annotated video.
-   Offering JSON and CSV downloads.
-   Showing warnings, uncertain results, and failures clearly.

The frontend must not run YOLO, ByteTrack, frame extraction, or other
heavy computer-vision processing in the browser.

### Backend API

The API should be responsible for:

-   Validating upload requests and video metadata.
-   Assigning server-generated IDs and filenames.
-   Registering video metadata.
-   Creating processing jobs.
-   Returning job IDs immediately rather than holding an HTTP request
    open for the entire video analysis.
-   Exposing job status and progress.
-   Exposing completed results and authorized file access.
-   Validating requests and returning predictable error responses.
-   Enforcing access controls if authentication/users are added later.

The API should not implement the detailed computer-vision algorithms
itself. It should call services and enqueue work.

### Background worker

The worker should:

-   Load configuration and the selected model.
-   Execute the pipeline outside the HTTP request lifecycle.
-   Update progress and processing stage.
-   Persist outputs and final results.
-   Record errors and mark the job failed if necessary.
-   Clean up temporary resources safely.
-   Support retries only when retrying is safe and outputs are handled
    idempotently.

Do not run lengthy video analysis directly inside a standard FastAPI
request handler. Video processing can exceed HTTP timeouts and consume
substantial CPU/GPU memory.

### Core pipeline

The pipeline must be independent of FastAPI and the frontend. It should
accept a video source plus a typed/configurable pipeline configuration
and return a structured result or a clear exception. It must not depend
on HTTP requests, browser sessions, frontend routes, or API response
objects.

### Persistence and storage

Keep metadata persistence separate from file storage.

-   **Database:** job state, video metadata, configuration snapshot,
    errors, metrics, wagon records, sequence, class counts, and output
    file references.
-   **File storage:** uploaded videos, annotated videos, JSON, CSV,
    logs, and optional intermediate artifacts.

Start with local storage and SQLite for development. Design interfaces
so PostgreSQL and cloud/object storage can be introduced later without
rewriting the pipeline.

------------------------------------------------------------------------

# 3. Recommended Technology Stack

Use a small, practical stack first:

-   **Python:** core implementation language.
-   **OpenCV:** video decoding, frame sampling, drawing, and video
    writing.
-   **YOLO / Ultralytics:** object detection using the current model
    weights.
-   **ByteTrack:** multi-object tracking, through a maintained and
    version-compatible implementation.
-   **NumPy:** array operations.
-   **Pandas:** optional CSV/reporting and analysis support.
-   **FastAPI:** HTTP API.
-   **Pydantic:** request/response schemas and configuration validation.
-   **SQLite initially:** local development metadata persistence.
-   **PostgreSQL later if needed:** multi-user/concurrent production
    persistence.
-   **Local filesystem initially:** video and result storage.
-   **Object storage later if needed:** scalable input/output file
    storage.
-   **Next.js + TypeScript later:** website frontend.
-   **Celery + Redis later if needed:** reliable job queue, retries, and
    multiple workers.
-   **PyTorch with CUDA if available:** GPU inference on compatible
    hardware.
-   **pytest:** automated tests.

Do not introduce Redis, Celery, cloud infrastructure, authentication, or
a complicated frontend before the core pipeline works unless a concrete
requirement demands them. Do not design the code so that adding them
later requires rewriting computer-vision modules.

------------------------------------------------------------------------

# 4. Target Repository / Folder Structure

Create the repository with this intended structure. Implement
pipeline-related files first, while preserving the API/worker/storage
boundaries shown here.

``` text
freight-wagon-system/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── logging.py
│   │   │   └── exceptions.py
│   │   ├── api/
│   │   │   ├── dependencies.py
│   │   │   └── routes/
│   │   │       ├── videos.py
│   │   │       ├── jobs.py
│   │   │       └── results.py
│   │   ├── schemas/
│   │   │   ├── video.py
│   │   │   ├── job.py
│   │   │   └── result.py
│   │   ├── services/
│   │   │   ├── video_service.py
│   │   │   ├── job_service.py
│   │   │   └── result_service.py
│   │   ├── pipeline/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── models.py
│   │   │   ├── video_reader.py
│   │   │   ├── detector.py
│   │   │   ├── tracker.py
│   │   │   ├── track_manager.py
│   │   │   ├── wagon_registry.py
│   │   │   ├── wagon_counter.py
│   │   │   ├── sequence_builder.py
│   │   │   ├── visualizer.py
│   │   │   ├── exporters.py
│   │   │   └── pipeline.py
│   │   ├── workers/
│   │   │   └── video_worker.py
│   │   ├── repositories/
│   │   │   ├── job_repository.py
│   │   │   └── result_repository.py
│   │   └── storage/
│   │       └── file_storage.py
│   ├── models/
│   │   └── best.pt
│   ├── tests/
│   │   ├── unit/
│   │   │   ├── test_video_reader.py
│   │   │   ├── test_detector_adapter.py
│   │   │   ├── test_track_manager.py
│   │   │   ├── test_wagon_registry.py
│   │   │   ├── test_wagon_counter.py
│   │   │   └── test_sequence_builder.py
│   │   └── integration/
│   │       ├── test_pipeline.py
│   │       └── test_api_jobs.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/                     # implement later
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── services/
│   │   │   └── api.ts
│   │   └── types/
│   ├── package.json
│   └── .env.example
├── data/                         # local development only; never commit data
│   ├── uploads/
│   ├── outputs/
│   ├── temp/
│   └── database/
├── docs/
│   ├── architecture.md
│   └── api.md
├── .gitignore
├── README.md
└── docker-compose.yml             # optional, add when needed
```

The tree describes intended module boundaries; not every placeholder
file must be fully implemented immediately. Create working modules in
phases rather than generating many empty files without behavior.

## Folder rules

-   `pipeline/`: computer-vision and domain logic; no FastAPI imports.
-   `api/`: HTTP routes only; keep route handlers thin.
-   `services/`: orchestration between routes, repositories, storage,
    and workers.
-   `workers/`: long-running job execution.
-   `repositories/`: persistence interfaces/implementations.
-   `storage/`: file access and storage backend abstraction.
-   `schemas/`: API request/response contracts; do not use API schemas
    as the pipeline's internal domain model.
-   `models/`: model weights and model metadata; large weights should
    normally be excluded from version control.
-   `data/`: local runtime data; exclude from version control.
-   `frontend/`: website code, added later. Do not make the backend
    depend on frontend implementation.
-   `tests/`: tests for individual algorithms and end-to-end behavior.

------------------------------------------------------------------------

# 5. Implementation Order --- Pipeline First, Website-Compatible from Day One

The agent must work in this order:

1.  Inspect the repository and available model files before changing
    anything.
2.  Create configuration, typed domain models, and interfaces for video
    input, detection, tracking, and outputs.
3.  Implement frame decoding/sampling.
4.  Implement the YOLO detector adapter.
5.  Implement the ByteTrack adapter.
6.  Implement track history and class stabilization.
7.  Implement wagon registry / track-fragment resolution.
8.  Implement wagon counting.
9.  Implement sequence generation.
10. Implement annotated video rendering.
11. Implement JSON and CSV export.
12. Implement the pipeline orchestrator and a local CLI entry point for
    testing.
13. Add unit and integration tests.
14. Add job persistence, file storage, and a background worker.
15. Add FastAPI endpoints and stable API contracts.
16. Implement the frontend later using those API contracts.

Do not start by building the frontend. Do not put all logic into one
giant `main.py`. Do not hardcode the current model's class list
throughout the application. The first goal is a testable pipeline that
is easy to invoke from both a local CLI and a background worker.

------------------------------------------------------------------------

# 6. Pipeline Configuration and Domain Models

## 6.1 Configuration

Create a validated configuration object. Suggested fields:

-   `model_path`
-   `target_fps` (initial default 30, configurable)
-   `confidence_threshold`
-   `iou_threshold` if exposed by detector/NMS configuration
-   `image_size` if supported by the chosen detector
-   ByteTrack settings, including high/low detection thresholds and
    track buffer where applicable
-   `device` (`cpu`, a supported CUDA device, or auto-detection)
-   `output_dir`
-   annotated-video output settings
-   optional counting-line coordinates and direction
-   minimum observations / confidence requirements for finalizing a
    wagon
-   logging level

Use documented library defaults when appropriate, but do not assume a
particular setting has the same name or behavior across library
versions. Verify the installed version's API.

Keep model path and settings in configuration, not scattered string
literals.

## 6.2 Domain models

Use typed models/dataclasses for the internal contracts. Exact fields
may evolve, but the following information must be represented.

### Video metadata

-   input video identifier and path/storage key
-   duration when known
-   original FPS when known
-   frame count when known
-   width and height
-   codec/metadata where available

### Frame sample

-   decoded frame/image array
-   original frame index
-   timestamp in seconds
-   width and height if not available from the image

### Detection

-   bounding box `[x1, y1, x2, y2]`
-   class ID
-   class name
-   confidence
-   frame index
-   timestamp

### Track observation

-   tracker ID
-   frame index and timestamp
-   bounding box
-   class prediction and confidence
-   tracker state/association information when available
-   optional quality/visibility metrics

### Wagon record

-   stable `wagon_uid` unique within a processing result
-   associated tracker IDs
-   final class and class confidence
-   first/last observed timestamp
-   first/last observed frame
-   spatial/position information needed for ordering
-   sequence position
-   count status
-   warning/uncertainty flags
-   supporting observation count

### Processing result

-   job/run identifier
-   input video metadata
-   model identity/version and configuration snapshot
-   processing status and timing
-   total resolved wagon count
-   type-wise counts
-   ordered wagon sequence
-   wagon-level records
-   output artifact references
-   warnings and unresolved identity cases

Use a stable distinction between: - `job_id`: one processing attempt. -
`video_id`: one uploaded source video. - ByteTrack `track_id`: a
tracker-assigned identity during a tracking run. - `wagon_uid`: a
resolved physical-wagon record within a result.

Never use a ByteTrack ID as the permanent wagon identity.

------------------------------------------------------------------------

# 7. Stage 1 --- Video Input, Validation, and Frame Sampling

Use OpenCV `VideoCapture` or an equivalent robust decoder to read the
video sequentially.

## Requirements

-   Verify that the file exists and is readable.
-   Verify that the decoder can open it.
-   Read metadata where available: FPS, dimensions, frame count,
    duration, codec.
-   Handle missing or invalid metadata safely.
-   Release video handles on success and failure.
-   Keep the original uploaded file unchanged.
-   Write generated files to a separate output directory.
-   Return clear errors for unsupported/corrupt input.
-   Avoid loading the entire video into memory.

## Sampling at 30 FPS

The initial target sampling rate is 30 FPS where appropriate, but it
must be configurable.

-   If the input is 60 FPS, sample approximately 30 frames per second.
-   If the input is 30 FPS, use the decoded frames at their natural
    cadence.
-   If the input is 25 FPS, do not manufacture five duplicate frames per
    second just to claim 30 FPS. Use actual decoded frames or a suitable
    lower target rate.
-   If frames are skipped, retain the original frame index and real
    timestamp.
-   Account for variable-frame-rate videos where possible; do not rely
    blindly on nominal FPS if reliable per-frame timestamps are
    available.
-   Document whether target FPS means sampling cadence or output video
    FPS.

For a constant-rate source, sample using timestamps/intervals rather
than assuming every input video has the same FPS.

Every sample should carry: - frame index - timestamp in seconds -
decoded image

Example at a 30 FPS cadence:

    Sample   Timestamp
  -------- -----------
         0     0.000 s
         1     0.033 s
         2     0.067 s
         3     0.100 s

These are illustrative timestamps.

## Do not

-   Assume all input videos have the same FPS.
-   Upsample low-FPS video by duplicating frames as the default
    behavior.
-   Discard timestamps or original frame indices.
-   Keep every decoded frame in RAM for a long video.
-   Overwrite the original input.

------------------------------------------------------------------------

# 8. Stage 2 --- YOLO Object Detection

Load the configured YOLO model once per worker/process or use a managed
model lifecycle. Do not reload model weights for every frame.

The detector should expose a stable interface so the underlying
model/library can be replaced without changing tracking or API code.

Suggested conceptual interface:

``` python
class Detector:
    def detect(self, frame, frame_index, timestamp):
        """Return normalized Detection objects for this frame."""
```

Use a real implementation/adapter for the selected installed YOLO
package; the snippet is conceptual, not a complete library-specific
implementation.

## Detection output

Each detection should include: - `[x1, y1, x2, y2]` - class ID - class
name - confidence - frame index - timestamp

## Requirements

-   Load class names from the loaded model or its configuration.
-   Do not hardcode the class list in unrelated modules.
-   Use a configurable confidence threshold.
-   Use suitable non-maximum suppression (NMS) behavior to reduce
    duplicate detections.
-   Preserve confidence and box coordinates for tracking.
-   Handle empty detections normally.
-   Handle inference errors clearly and log relevant context.
-   Record model path/version and inference settings with the job.
-   Allow the temporary model to be replaced with the future larger-data
    model through configuration.

The project's class set has previously included `BCACBM`, `BCN`, `BLC`,
`BOXN`, `BTPN`, `Brake_Van`, and `Locomotive`. This is only an example
from an earlier dataset configuration. Inspect the actual
model/configuration; do not assume the list is final or complete.

## Example detection representation

``` json
{
  "frame_index": 120,
  "timestamp": 4.0,
  "bbox": [240, 130, 590, 430],
  "class_id": 3,
  "class_name": "BOXN",
  "confidence": 0.91
}
```

This is illustrative data, not a real model prediction.

## Do not

-   Assume the example class ID is always correct for `BOXN`.
-   Make the tracker depend on a particular class order.
-   Confuse a model detection with a distinct wagon.
-   Claim that a larger dataset alone guarantees correct counting or
    tracking.
-   Silently discard all uncertain detections without recording enough
    information for evaluation.

------------------------------------------------------------------------

# 9. Stage 3 --- ByteTrack Integration

Process frames chronologically. Pass detections for each sampled frame
to ByteTrack and collect track outputs.

ByteTrack associates detections across frames and returns tracker IDs.
It does not classify wagons by itself, and it does not provide a
guaranteed final wagon count.

Use a maintained implementation compatible with the selected detector
and library versions. Verify its actual API, expected detection format,
coordinate convention, frame-rate assumptions, and track-buffer behavior
before implementing the adapter.

## Requirements

-   Keep tracker logic behind `tracker.py`.
-   Normalize input/output formats in the adapter.
-   Process frames in temporal order.
-   Preserve tracker IDs and observations.
-   Configure thresholds and track buffer where supported.
-   Handle frames with zero detections.
-   Log tracking failures without corrupting the job result.
-   Keep track IDs scoped to a single processing run.
-   Test tracker behavior under brief occlusion, missed detections, and
    similar adjacent wagons.

Example (illustrative):

    Frame   Track ID Class prediction     Confidence
  ------- ---------- ------------------ ------------
      120          7 BOXN                       0.91
      121          7 BOXN                       0.88
      122          7 BCN                        0.93
      120          8 BCN                        0.84
      121          8 BCN                        0.89

The repeated tracker ID means the tracker associates detections with the
same track. It does not prove that the physical identity is always
correct.

## Important limitation

A physical wagon may receive multiple tracker IDs if it disappears from
view or becomes occluded. Two similar adjacent wagons may also be
confused. Do not blindly count unique tracker IDs.

------------------------------------------------------------------------

# 10. Stage 4 --- Track History and Class Stabilization

Maintain a history of observations for each track. Do not keep only the
latest box/class.

Record, as available: - frame index and timestamp - tracker ID - box -
class prediction - class confidence - tracker state - optional
visibility/detection-quality indicators

## Class stabilization

A class may fluctuate across frames. For example, one track may have
predictions `BOXN`, `BOXN`, `BCN`, `BOXN`, `BOXN`. Do not finalize the
wagon class from one noisy observation.

A suitable first approach is confidence-weighted voting:

\[ S(c) = `\sum`{=tex}\_{i=1}\^{N} w_i p_i(c) \]

Where: - `c` is a class. - `p_i(c)` is the model score/confidence
associated with class `c` for observation `i`, if the detector exposes
compatible class scores. - `w_i` is an observation weight based on
reliability/visibility if such a measure is available.

If the model API only returns the top predicted class and confidence,
use a consistent weighted-vote approximation. Do not pretend a top-class
confidence is a full calibrated probability distribution over all
classes.

Choose the class with the strongest aggregate evidence only when minimum
evidence/consistency requirements are satisfied. Otherwise mark the
class uncertain.

Potential track states: - `tentative`: newly observed, insufficient
evidence. - `confirmed`: enough reliable observations. -
`temporarily_lost`: missing from recent frames but potentially
recoverable. - `completed`: no longer observed and ready for
finalization. - `duplicate_candidate` or `ambiguous`: may overlap with
another track/physical wagon.

The implementation can define its own state model; do not assume
ByteTrack exposes all these exact states.

------------------------------------------------------------------------

# 11. Stage 5 --- Wagon Registry and Track-Fragment Resolution

This is a key custom component. Create a `WagonRegistry` that maintains
one record for each resolved physical wagon, distinct from ByteTrack's
short-term track IDs.

Example failure case: 1. A wagon is tracked as ID 7. 2. It becomes
occluded and ID 7 is lost. 3. The same wagon reappears as ID 21. 4.
Naive unique-ID counting counts it twice.

The registry should associate one or more track IDs with a stable
`wagon_uid` when evidence supports that they refer to the same physical
wagon.

## Useful matching evidence

-   temporal gap and overlap constraints
-   last known position and predicted motion
-   bounding-box size and location
-   direction of travel
-   class compatibility, while allowing noisy class predictions
-   visual appearance/embeddings if later implemented
-   plausible object movement through the camera view
-   whether both candidate tracks coexist at the same time (simultaneous
    tracks usually indicate distinct objects)

IoU (intersection over union) and motion prediction can help compare
boxes/tracks. Appearance-based re-identification may help with difficult
occlusion but is not required for the first prototype.

## Conservative behavior

-   Do not merge tracks merely because they have the same class.
-   Do not merge tracks merely because they are close in time.
-   Do not merge tracks that have evidence of simultaneous distinct
    physical wagons.
-   If identity is ambiguous, preserve the ambiguity as a warning/review
    candidate rather than silently making an irreversible merge.
-   Make matching thresholds configurable and test them on real videos.
-   Keep a record of which tracker IDs contributed to each wagon record.
-   Make registry updates deterministic where possible.

## Wagon record fields

At minimum: - `wagon_uid` - associated `track_ids` - final class and
class confidence - first and last observed timestamps - first and last
observed frame - positional information used for sequence ordering -
sequence position when finalized - counted/not-counted status -
uncertainty flags/reason - supporting observation count

The registry is an estimate based on visual evidence, not an absolute
guarantee of physical identity.

------------------------------------------------------------------------

# 12. Stage 6 --- Wagon Counting

The final total must be calculated from resolved wagon records, not raw
detections and not the number of tracker IDs.

Two possible counting strategies are supported.

## Method A: Resolved unique-wagon registry

Use this for general video analysis. Finalize a wagon record when
sufficient evidence exists that the object has left the view or its
track has ended. Count each resolved wagon record once.

Advantages: - works with a variety of camera setups - supports
full-video analysis - naturally connects to wagon-level results and
sequence output

Risks: - tracker ID fragments can cause double counts - occlusion and
poor detections can create identity uncertainty

## Method B: Virtual counting line

For a fixed camera watching a train pass in one direction, define a
virtual line. Count a wagon when its representative point crosses the
line in the expected direction and the crossing passes validation.

Requirements: - configurable line coordinates - expected direction of
travel - a per-wagon counted flag - track continuity and direction
validation - prevent repeat counts when a track jitters around the
line - avoid counting both the same wagon and its track fragment -
consider box instability and adjacent wagon overlap

A bounding-box center crossing is a practical starting point, not a
universal solution. Test the anchor point and crossing logic for the
camera perspective.

## Recommendation

Start with the resolved wagon registry. If the deployment scenario is a
fixed camera and a train passes in one direction, add line-crossing as a
configurable counting mode. Record the selected counting convention in
job configuration and output metadata.

## Count integrity

Class-wise counts should sum to the total count only when every counted
wagon has one final class and all classes are included. If
unknown/uncertain class records are allowed, include an explicit
`Unknown`/`Unresolved` bucket or explain why the class-wise total
differs.

Do not silently drop unresolved records from the count or report.

------------------------------------------------------------------------

# 13. Stage 7 --- Wagon Sequence Generation

Do not derive wagon order from YOLO's detection array order or from the
left-to-right order of boxes in one arbitrary frame.

The sequence builder should use finalized wagon records, their
timestamps, and spatial/track histories.

## Define the sequence convention

### Fixed camera, train passes the camera

Use validated crossing-event timestamps. This naturally produces order
of appearance at the line. If the locomotive appears first, it is first
in the appearance sequence.

### Train visible over an extended period

Use consistent spatial relationships and temporal track history.
Establish the direction of travel and define whether output means
front-to-rear or rear-to-front.

### Partial video

The first or last wagon may be outside the video. Mark the sequence as
partial when the available evidence cannot establish the full train
order.

### Reverse travel direction

Chronological crossing order can be the reverse of physical
front-to-rear order. Document the convention and, if necessary, provide
both appearance order and inferred physical order.

Each sequence item should include: - `position` - `wagon_uid` -
`class_name` - first/validated crossing timestamp where applicable -
confidence/uncertainty status

Do not claim a complete or certain sequence when the video only shows
part of the train or wagon identities remain ambiguous.

------------------------------------------------------------------------

# 14. Stage 8 --- Annotated Video and Exports

## Annotated video

Draw, as appropriate: - bounding boxes - class labels - detection
confidence - tracker ID (clearly distinguish from `wagon_uid`) -
optional stable wagon ID - optional virtual counting line - optional
running count and processing status

Do not make the video imply greater certainty than the data supports.
Avoid displaying a finalized wagon identity before the registry has
enough evidence; if provisional IDs are shown, label them as
provisional.

Preserve an appropriate output frame rate and dimensions. Choose a
supported output codec/container and check that the writer opens
successfully. Ensure output writing is completed and the writer is
released even if processing fails.

## JSON

Save a structured result with: - job/run ID - input metadata -
model/configuration snapshot - processing status and timing - total
count - type-wise counts - sequence - wagon records -
uncertainty/warning information - references to output files

## CSV

Provide a sequence table with fields such as: - sequence position -
wagon UID - final class - class confidence - first observed timestamp -
crossing timestamp if applicable - associated track IDs - uncertainty
flag

The exact CSV columns can evolve, but the CSV must preserve enough
information to interpret the sequence and review questionable records.

## Example output summary

``` text
Total detected wagons: 42
```

Illustrative type counts:

  Wagon type                  Count
  ------------------------- -------
  BOXN                           18
  BCN                            10
  BTPN                            5
  BLC                             4
  Brake_Van                       1
  Locomotive                      1
  Other supported classes         3
  Total                          42

These numbers are examples only, not model results. Counts must be
computed from actual finalized records.

Illustrative sequence:

``` text
Locomotive -> BOXN -> BOXN -> BCN -> BTPN -> BLC -> Brake_Van
```

------------------------------------------------------------------------

# 15. Pipeline Orchestrator and CLI

Create a `pipeline.py` that orchestrates modules without containing
every algorithm.

Conceptual flow:

``` python
def process_video(video_source, config, progress_callback=None):
    metadata = inspect_video(video_source)
    detector = create_detector(config)
    tracker = create_tracker(config)
    track_manager = TrackManager(config)
    wagon_registry = WagonRegistry(config)

    for sample in read_video_frames(video_source, config):
        detections = detector.detect(
            sample.image,
            sample.frame_index,
            sample.timestamp,
        )
        tracks = tracker.update(detections, sample)
        track_manager.update(tracks, sample)
        wagon_registry.update(track_manager, sample)

        # Update progress and write annotated frames through
        # dedicated interfaces; avoid coupling the pipeline to HTTP.

    track_manager.finalize()
    wagon_registry.finalize(track_manager)

    count_result = calculate_counts(wagon_registry)
    sequence = build_sequence(wagon_registry, config)
    artifacts = write_outputs(...)

    return build_processing_result(
        metadata=metadata,
        counts=count_result,
        sequence=sequence,
        artifacts=artifacts,
    )
```

This is pseudocode. Implement real functions and data types, use the
selected library's real APIs, and handle exceptions/resources. Do not
copy this snippet expecting it to execute as-is.

Provide a local CLI command so the pipeline can be tested without the
API, for example:

``` bash
python -m app.cli process \
  --input data/uploads/sample.mp4 \
  --output data/outputs/sample \
  --config path/to/config.yaml
```

The exact CLI implementation and arguments can vary, but local
processing must not require starting the website.

## Progress callback

Allow the pipeline to report progress through an optional callback or
event interface, such as: - current stage - frames processed - total
frames if known - percentage when calculable - human-readable message

The core pipeline must not import FastAPI to report progress. A worker
can translate these events into database/job status updates.

------------------------------------------------------------------------

# 16. Website API Contract

Design stable API routes early, even if implemented after the pipeline.

Suggested versioned routes:

  ------------------------------------------------------------------------------------------
  Method                  Route                                      Purpose
  ----------------------- ------------------------------------------ -----------------------
  `POST`                  `/api/v1/videos`                           Upload and register
                                                                     video

  `POST`                  `/api/v1/jobs`                             Create a processing job

  `GET`                   `/api/v1/jobs/{job_id}`                    Get status and progress

  `GET`                   `/api/v1/jobs/{job_id}/results`            Retrieve counts and
                                                                     sequence

  `GET`                   `/api/v1/jobs/{job_id}/video`              Stream/access annotated
                                                                     video

  `GET`                   `/api/v1/jobs/{job_id}/exports/{format}`   Download JSON or CSV
  ------------------------------------------------------------------------------------------

The upload endpoint can return a `video_id`; the job-creation endpoint
should accept that ID and return a `job_id`. Separate upload and
processing so videos can be validated before compute is scheduled.

## Job states

Use a documented finite set, for example: - `queued` - `validating` -
`processing` - `finalizing` - `completed` - `failed` - optionally
`cancelled`

Use one consistent status vocabulary across database, API, worker, and
frontend.

## Example status response

``` json
{
  "job_id": "job_001",
  "status": "processing",
  "progress": 62,
  "current_stage": "object_tracking",
  "message": "Tracking wagons across video frames"
}
```

## Example result response

``` json
{
  "job_id": "job_001",
  "status": "completed",
  "total_wagons": 42,
  "type_counts": {
    "BOXN": 18,
    "BCN": 10,
    "BTPN": 5,
    "BLC": 4
  },
  "sequence": [
    {
      "position": 1,
      "wagon_id": "W001",
      "class_name": "Locomotive"
    },
    {
      "position": 2,
      "wagon_id": "W002",
      "class_name": "BOXN"
    }
  ],
  "annotated_video_url": "/api/v1/jobs/job_001/video"
}
```

These examples are illustrative. The implementation must use real
values, consistent totals, correct URL authorization, and actual file
availability.

## API rules

-   Use Pydantic request/response schemas.
-   Return appropriate HTTP status codes and predictable error payloads.
-   Validate input size, format, and content.
-   Do not return local absolute filesystem paths to the browser.
-   Return an API route or short-lived authorized URL for artifacts.
-   Do not keep a request open until a long video finishes.
-   Make job creation idempotent where practical, or prevent accidental
    duplicate job submission from frontend retries.
-   Version the API under `/api/v1`.
-   Document all routes in `docs/api.md`.
-   Configure CORS narrowly for the expected frontend origin when
    deployed; do not enable unrestricted origins with credentials.

------------------------------------------------------------------------

# 17. Background Worker, Repositories, and Storage

## Worker

The worker should: 1. Load a queued job. 2. Mark it as
validating/processing. 3. Resolve the input video through the storage
interface. 4. Load the job's configuration/model selection. 5. Run the
pipeline. 6. Save outputs. 7. Persist result data and output references.
8. Mark the job completed, or failed with a useful error. 9. Release
model/video/output resources.

For the first local version, a separate worker process or simple queue
may be enough. If concurrent jobs, retries, or multiple workers are
required, adopt Celery + Redis or another appropriate queue. Keep the
queue implementation outside the pipeline.

## Repository interfaces

`job_repository.py` should abstract job persistence: - create job - get
job - update state/progress - record failure - mark completion

`result_repository.py` should abstract results persistence: - save
processing result - retrieve result by job ID - retrieve wagon
records/sequence - retrieve class counts

The pipeline must not issue SQL queries directly.

## File storage interface

`file_storage.py` should abstract: - saving an upload - resolving an
input video - writing or registering output artifacts - getting an
authorized artifact reference - deleting files under a defined retention
policy

Start with local filesystem storage. Later, an object-storage adapter
can implement the same interface.

## Persistence expectations

The website must be able to retrieve results after: - the worker exits -
the API process restarts - the user refreshes the page - the processing
job completes

Do not keep the only copy of results in a Python global variable or
worker memory.

------------------------------------------------------------------------

# 18. Security, Reliability, and Resource Management

Implement these from the beginning where relevant:

-   Set a maximum upload size.
-   Validate extension and actual file content; do not trust the
    filename alone.
-   Generate filenames and IDs on the server.
-   Prevent path traversal; never use an untrusted filename as an
    unrestricted filesystem path.
-   Keep uploads, model weights, logs, and results out of public static
    directories.
-   Restrict result access to the authorized user/job if multi-user
    support is added.
-   Add retention/cleanup rules for temporary files and old outputs.
-   Handle corrupt video, empty video, missing model, unsupported codec,
    disk-full, inference failure, and worker interruption.
-   Release `VideoCapture` and `VideoWriter` resources reliably.
-   Avoid loading an entire video into memory.
-   Limit concurrent inference jobs based on CPU/GPU memory and hardware
    capacity.
-   Record clear error messages for logs without exposing secrets or
    sensitive local paths in public API responses.
-   Never commit secrets, `.env` files, private videos, generated output
    files, or large model weights by default.
-   Add `.gitignore` entries for `.env`, caches, `data/`, generated
    videos, logs, and model weights as appropriate.

------------------------------------------------------------------------

# 19. Testing and Validation Plan

Do not decide that the system works solely because the annotated video
looks convincing. The total count and sequence can be wrong even when
boxes appear reasonable.

Create manually verified test videos with: - true wagon count - true
class for each wagon where identifiable - reference sequence -
partial/occluded wagons noted - lighting and image-quality notes -
camera position and direction of travel

Use held-out videos that were not used for model training.

## Metrics

-   Detection precision and recall.
-   Per-class precision and recall.
-   Tracking ID switches and track fragmentation.
-   Count absolute error: `abs(predicted_count - true_count)`.
-   Sequence accuracy or normalized edit distance.
-   Processing throughput/FPS and total processing time.
-   Percentage of unresolved/uncertain wagon records.

## Tests to write

### Unit tests

-   video sampling preserves timestamps/frame indices
-   detector adapter normalizes empty and non-empty outputs
-   tracker adapter handles empty frames
-   class aggregation resists a single noisy prediction
-   wagon registry does not merge simultaneous distinct tracks
-   duplicate/fragment handling follows configured rules
-   counting counts each resolved wagon once
-   class-wise counts reconcile with total under the documented policy
-   sequence order follows the configured convention
-   JSON/CSV output schema is valid

### Integration tests

-   run the complete pipeline on a small sample video
-   ensure output video is created and readable
-   ensure JSON and CSV are created
-   ensure API job state transitions correctly
-   ensure a completed result can be fetched after worker completion
-   ensure failures mark jobs failed and release resources

Use deterministic synthetic tests for counting and sequence logic where
possible. Do not depend exclusively on real model inference for all unit
tests.

------------------------------------------------------------------------

# 20. Performance and Model Replacement

The temporary model is suitable for pipeline development. The future
model trained on a larger dataset should be replaceable through
configuration.

When replacing the model: - update the configured model
path/identifier - inspect its class names and class-ID mapping -
validate on held-out videos - retune confidence/NMS thresholds if
needed - re-evaluate ByteTrack settings because detection quality
affects tracking - re-evaluate count and sequence accuracy - preserve
model identity/configuration with every job result

Do not assume the new model will automatically fix: - ByteTrack ID
switches - track fragmentation - duplicate wagon identities -
counting-line errors - incorrect sequence convention

These are separate concerns and must be tested separately.

## FPS and performance

Thirty FPS is the initial target, not a universal requirement. Benchmark
10, 15, and 30 FPS sampling if suitable for the video. The best cadence
depends on wagon speed, camera angle, motion blur, visibility, and
hardware.

If processing is too slow: - benchmark before optimizing - consider GPU
inference where supported - reduce unnecessary image copies - avoid
retaining all frames/detections in memory - consider batched detector
inference only if it does not break the tracker's chronological input
expectations - keep tracking updates in the correct temporal order -
separate video decoding, inference, and output-writing bottlenecks in
measurements

------------------------------------------------------------------------

# 21. Website UI Requirements for Later

The website can initially have these pages/components:

1.  **Upload page:** video picker, supported formats/size guidance,
    upload progress, validation errors.
2.  **Jobs page:** queued/running/completed/failed jobs.
3.  **Processing detail page:** progress, current stage, status
    messages, failure reason if applicable.
4.  **Results summary:** total count, class-wise counts, chart.
5.  **Sequence table:** position, wagon UID, class, confidence,
    timestamp, warning/uncertainty.
6.  **Annotated video player:** output video with boxes, labels, and
    IDs.
7.  **Exports:** download JSON and CSV.
8.  **Warnings/review panel:** ambiguous identities, partial train,
    unresolved classes, or processing limitations.

The frontend must consume the documented API. It must not duplicate
business logic such as class aggregation or wagon counting in
TypeScript. The backend is the source of truth for results.

------------------------------------------------------------------------

# 22. Do / Do Not Checklist for the Coding Agent

## Do

-   Inspect existing files and model artifacts before modifying
    anything.
-   Implement the core pipeline first, but design it to be callable from
    a worker.
-   Keep the pipeline independent from FastAPI and the frontend.
-   Use small, focused modules with typed interfaces.
-   Keep settings configurable.
-   Preserve timestamps and original frame indices.
-   Load the model once per worker/process, not per frame.
-   Normalize detector and tracker outputs into project-owned data
    models.
-   Maintain track history and aggregate class predictions.
-   Distinguish tracker IDs from physical wagon UIDs.
-   Make track-fragment matching conservative and auditable.
-   Document the wagon sequence convention.
-   Persist status, results, and artifact references.
-   Write unit and integration tests.
-   Validate the output on manually counted held-out videos.
-   Provide a local CLI to run the pipeline without the website.
-   Record model/configuration metadata for each processing job.
-   Report uncertainty rather than hiding ambiguous results.

## Do not

-   Put all processing logic in one large script or `main.py`.
-   Import FastAPI from core pipeline modules.
-   Run long video processing synchronously in a normal API request.
-   Count raw detections as wagons.
-   Count unique ByteTrack IDs as a guaranteed wagon count.
-   Assume one tracker ID always maps to one physical wagon.
-   Merge tracks solely because class labels match.
-   Derive sequence from detector output order or one frame's box order.
-   Hardcode a fixed class list or class-ID mapping throughout the code.
-   Assume all input videos have the same FPS.
-   Create duplicate frames merely to force a lower-FPS source to 30
    FPS.
-   Load every frame into RAM for long videos.
-   Keep the only results in memory.
-   Expose filesystem paths directly to the website.
-   Trust user-supplied filenames or paths.
-   Claim certainty when wagon identity/order is ambiguous.
-   Add unnecessary infrastructure before the core system is validated.
-   Replace the current model without checking class mapping and
    revalidating tracking/counting/sequence behavior.

------------------------------------------------------------------------

# 23. Definition of Done

The first usable backend/pipeline milestone is complete when:

-   [ ] The project structure exists and dependencies are documented.
-   [ ] A local command can process a video without starting the
    website.
-   [ ] Video metadata and sampled frame timestamps are preserved.
-   [ ] YOLO detections use a configurable model and class mapping.
-   [ ] ByteTrack processes detections chronologically.
-   [ ] Track histories and class stabilization are implemented.
-   [ ] A wagon registry separates physical-wagon records from tracker
    IDs.
-   [ ] Counting and sequence generation use wagon-level records.
-   [ ] Ambiguous identity/class/order cases are surfaced as warnings.
-   [ ] An annotated video is written successfully.
-   [ ] JSON and CSV results are produced.
-   [ ] Unit tests cover aggregation, counting, and sequence rules.
-   [ ] A manually verified sample video has been evaluated.
-   [ ] The pipeline returns a structured result and can report progress
    without importing FastAPI.
-   [ ] Input/output storage is abstracted so it can be changed later.

The website-integration milestone is complete when:

-   [ ] FastAPI exposes versioned upload, job, result, and artifact
    endpoints.
-   [ ] Long-running work runs in a worker rather than the request
    handler.
-   [ ] Job state and results persist in a database.
-   [ ] Artifacts are stored and retrieved through the storage
    abstraction.
-   [ ] The frontend can upload a video, poll job status, and display
    results.
-   [ ] Errors, warnings, and authorization are handled appropriately.

------------------------------------------------------------------------

# 24. Final Instruction to the Agent

Implement a robust, modular, testable backend for freight-wagon
detection, tracking, counting, and sequence generation. The long-term
target is a website with video upload and a results dashboard, so every
module must fit the API/worker/storage architecture described in this
document.

**Start with the pipeline files and domain interfaces, not the
frontend.** Make the core pipeline independently runnable from a CLI,
then add persistence, a background worker, and FastAPI endpoints. Do not
implement unverified heuristics as if they guarantee physical wagon
identity. Clearly label assumptions, add tests, and report uncertainty.
Keep the current YOLO model replaceable by configuration.

When working in an existing repository, inspect it first, preserve
useful work, and make incremental changes. Do not overwrite existing
files or model artifacts without checking their contents and purpose.
Verify library versions and actual APIs rather than inventing method
names. At the end of each implementation phase, run the relevant tests
and report what was implemented, what passed, what remains incomplete,
and any assumptions that need confirmation.
