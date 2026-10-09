# Freight Train Intelligence Platform

Detects Indian freight wagon types in a train video, tracks them across frames, resolves
distinct physical wagons, counts them, determines their order, and writes an annotated
video plus JSON/CSV results. This repository currently contains the **backend processing
pipeline** (runnable locally from the command line). The FastAPI service, job worker and
website are planned on top of it — see `documentation/freight_wagon_system_agent_reference.md`.

## Setup (Windows, Python 3.11)

```bash
python3.11 -m venv .venv          # or: py -3.11 -m venv .venv
.venv\Scripts\activate
pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu130
pip install -r backend/requirements-dev.txt
```

Use the CPU index (`https://download.pytorch.org/whl/cpu`) on machines without an NVIDIA GPU;
the pipeline picks the GPU automatically when available (`--device cpu` forces CPU).

### Model weights

The trained detector lives in `backend/models/best.pt` (YOLO11s fine-tuned, 8 classes:
`BCACBM, BCN, BLC, BOXN, BTPN, Brake_Van, Flat_Wagon, Locomotive`). Class names are always
read from the model file, so a future model can be dropped in with `--model` or
`detector.model_path` in the config. Print what a weights file contains with:

```bash
cd backend
python -m app.cli inspect-model --model models/best.pt
```

## Run the pipeline

All commands run from the `backend/` directory.

```bash
python -m app.cli process --input "D:/videos/train.mp4"
```

Outputs go to `data/outputs/<run_id>/` (git-ignored). Useful options:

| Option | Meaning |
|---|---|
| `--model PATH` | Weights file (default `backend/models/best.pt`) |
| `--config PATH` | YAML config (default `backend/configs/default.yaml`) |
| `--output-dir DIR` / `--run-dir DIR` | Parent folder for runs / exact folder for this run |
| `--target-fps N` | Analysis cadence (default 30). Lower-rate videos are never upsampled. |
| `--conf`, `--iou`, `--imgsz`, `--device` | Detector settings |
| `--track-buffer SECONDS` | How long ByteTrack keeps a lost track |
| `--counting-mode registry\|line` | Count resolved wagons, or only wagons crossing the reference line |
| `--line-position F`, `--travel-axis auto\|x\|y` | Reference/counting line (fraction of frame) and axis |
| `--max-frames N`, `--no-video`, `--quiet`, `--log-level` | Quick runs and verbosity |

**Locomotives are not counted as wagons**: they are detected, tracked and shown in the sequence, but the
headline "Total wagons" excludes the classes in `counting.exclude_from_wagon_total` (default
`[Locomotive]`). Objects that don't move with the passing train (e.g. stock parked on another track)
are reported as `not_counted_stationary`. Every other setting (class-vote thresholds,
fragment-matching tolerances, minimum evidence, …) is in
`backend/configs/default.yaml`. Exit codes: 0 ok, 2 bad input/config, 3 model, 4 processing/output.

### Outputs

| File | Content |
|---|---|
| `annotated.mp4` | Sampled frames with final wagon UID, class, sequence position, tracker ID, reference line |
| `result.json` | Metadata, model + config snapshot, counts, sequence, wagon records, warnings |
| `wagons.csv` | One row per wagon record, in sequence order (spreadsheet friendly) |
| `tracks.csv` | Per-frame observations behind every wagon (for review/evaluation) |
| `summary.txt`, `run.log` | Human-readable summary and full debug log |

Schemas, flags and the sequence convention are documented in `documentation/output_schema.md`.

## How it works

```
video ─► frame sampler ─► YOLO detector ─► ByteTrack ─► track histories
             (timestamps,     (adapter)      (identity)    (class votes)
              frame indices)
                                                   │
        annotated video ◄─ renderer ◄─ sequence ◄─ counter ◄─ wagon registry
        JSON / CSV      ◄─ exporters                         (split / merge / link fragments)
```

* **Detection ≠ wagon, tracker ID ≠ wagon.** The wagon registry turns tracker IDs into
  `wagon_uid`s: it splits IDs that jump between wagons, merges concurrent duplicate boxes, and
  re-links fragments after occlusion only when the motion evidence is unique and consistent.
  Ambiguous cases are kept separate and flagged, never silently merged.
* **Class** = confidence-weighted vote across all observations; split votes become `Unresolved`.
* **Sequence** = order in which wagons pass a reference line (mid-frame by default): position 1 is
  the leading end in the direction of travel. Whether that is the physical front is not claimed.
  Partial trains (already in view at the start / still in view at the end) are reported as such.
* The video is processed twice: pass 1 detects and tracks (no frames kept in memory), pass 2
  renders the annotated video with the final, resolved identities.

Code: `backend/app/pipeline/` (no web-framework imports; callable from a future worker via
`app.pipeline.process_video(path, config, progress=callback)`).

## Tests

```bash
cd backend
python -m pytest              # unit + synthetic end-to-end + model smoke tests
```

Real-video test with a manual ground truth (optional):

```bash
set WAGON_SAMPLE_VIDEO=D:\videos\train.mp4
set WAGON_EXPECTED_COUNT=62
set WAGON_EXPECTED_SEQUENCE=Locomotive,Locomotive,BOXN,...
python -m pytest tests/integration/test_real_video.py
```

## Known limitations

* Accuracy depends on the detector. On sample footage the current model missed most empty
  flat wagons in one clip, labelled a distant container wagon as `Locomotive`, and appears to box
  individual containers rather than whole container wagons — counts on such footage will be wrong
  regardless of tracking. Evaluate on manually counted, held-out videos.
* Fragment matching assumes roughly constant motion during short occlusions; a train that stops
  and reverses is flagged `direction_inconsistent` rather than handled.
* The annotated video plays the *sampled* frames at the effective sampling rate.
