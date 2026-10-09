# Pipeline Output Schema (schema_version 1.0)

Every run writes into its own folder, by default `data/outputs/<run_id>/`:

| File | Content |
|---|---|
| `result.json` | Complete structured result (always written, also for failed runs) |
| `wagons.csv` | One row per resolved wagon record (sequence order first, then not-counted records) |
| `tracks.csv` | Every per-frame observation used, with its wagon UID and tracker ID (for review/evaluation) |
| `annotated.mp4` | Annotated sampled frames, played back at the effective sampling rate |
| `summary.txt` | Human-readable summary (same text the CLI prints) |
| `run.log` | DEBUG-level log of the run |

All paths inside `result.json` → `artifacts` are relative to the run folder.

## Identifiers

| Name | Meaning |
|---|---|
| `run_id` | One processing attempt (`YYYYMMDD_HHMMSS_xxxxxx`). Becomes the job ID once a job system exists. |
| `track_id` | ByteTrack identity, scoped to one run. **Not** a wagon identity. |
| `wagon_uid` | Resolved physical-wagon record (`W001`, …), numbered by first appearance; unique within one result. |

## Sequence convention

`sequence_info.convention` is one of:

* `passage_order_at_reference_line` (default, `counting.mode = registry`): wagons are ordered by the time their
  box centre passes a reference line across the travel axis (`counting.line_position`, default mid-frame).
  Position 1 is the **leading end of the train in its direction of travel**. Whether that is the physical
  front (locomotive pulling) or rear (pushing) is **not** determined.
* `line_crossing_order` (`counting.mode = line`): same line, but only wagons with a validated crossing (with
  hysteresis, in the travel direction) are counted and ordered.
* `spatial_order_along_axis`: fallback when no consistent motion is found (stationary train): order by mean
  position along the travel axis (left→right or top→bottom).

If a wagon was never seen crossing the reference line, its crossing time is extrapolated from its fitted
motion and the wagon is flagged `sequence_extrapolated`.

`sequence_info.completeness`: `complete` (no counted wagon visible within `counting.boundary_seconds` of the
video start/end), `partial_start`, `partial_end`, `partial_both`, or `empty`.

## result.json

```jsonc
{
  "schema_version": "1.0",
  "run_id": "20261009_203000_ab12cd",
  "status": "completed",                 // or "failed"
  "error": null,                         // "<ErrorType>: message" when failed
  "input": {"path": "...", "width": 1920, "height": 1080, "fps": 30.0, "frame_count": 900,
            "duration_seconds": 30.0, "codec": "avc1", "file_size_bytes": 12345678},
  "model": {"adapter": "ultralytics", "framework_version": "8.4.x", "model_file": "best.pt",
            "sha256": "...", "device": "0", "num_classes": 8,
            "class_names": {"0": "BCACBM", "...": "..."}, "checkpoint": {"trained_date": "...", "...": "..."}},
  "config": { /* full configuration snapshot + resolved_model_path + tracker_runtime */ },
  "sampling": {"source_fps": 30.0, "target_fps": 30.0, "effective_fps": 30.0, "decoded_frames": 900,
               "sampled_frames": 900, "timestamp_source": "decoder", "timestamp_fallbacks": 0,
               "stopped_early": false, "detections_total": 4321,
               "output_video": {"codec": "mp4v", "fps": 30.0, "frames": 900}},
  "timing_seconds": {"setup": 1.2, "pass1_detect_track": 40.1, "inference": 35.0, "tracking": 1.1,
                     "resolution": 0.05, "export": 0.02, "render": 9.8, "total": 51.3},
  "counts": {
    "mode": "registry",
    "total_counted": 42,                 // counted wagon records (all classes incl. Unresolved)
    "wagons_only_total": 41,             // total minus counting.exclude_from_wagon_total classes
    "excluded_classes": ["Locomotive"],
    "type_counts": {"BOXN": 18, "BCN": 10, "Unresolved": 1},   // always sums to total_counted
    "not_counted": 3,                    // records reported but not counted (see count_status)
    "tracker_ids_seen": 51
  },
  "sequence_info": {"convention": "...", "completeness": "...", "uncertain_items": 2,
                    "order_string": "Locomotive -> BOXN -> ...", "notes": ["..."],
                    "travel_axis": "x", "travel_direction": "left_to_right",
                    "reference_line_px": 960.0, "moving_wagons": 42,
                    "direction_inconsistent_wagons": []},
  "sequence": [
    {"position": 1, "wagon_uid": "W001", "class_name": "Locomotive", "class_confidence": 0.97,
     "reference_time": 3.214, "crossing_time": 3.214, "first_seen": 1.1, "uncertain": false, "flags": []}
  ],
  "wagons": [ /* see below; every tracker ID appears in exactly one wagon record */ ],
  "warnings": ["..."],
  "unresolved_identities": [
    {"type": "ambiguous_fragment | duplicate_candidate | duplicate_conflict",
     "track_ids": [7, 21], "wagon_uids": ["W005", "W006"], "detail": "..."}
  ],
  "artifacts": {"log": "run.log", "result_json": "result.json", "wagons_csv": "wagons.csv",
                "tracks_csv": "tracks.csv", "annotated_video": "annotated.mp4", "summary": "summary.txt"}
}
```

### Wagon record

| Field | Meaning |
|---|---|
| `wagon_uid`, `sequence_position` | Identity and 1-based order (null if not counted) |
| `class_name` | Final class, or `Unresolved` if evidence is insufficient/inconsistent |
| `class_confidence` | Winning share of confidence-weighted top-1 votes (not a calibrated probability) |
| `class_best_guess`, `class_runner_up`, `class_distribution` | Vote details for review |
| `mean_detection_confidence`, `supporting_observations` | Detector confidence / count for the winning class |
| `count_status` | `counted`, `not_counted_insufficient_evidence`, `not_counted_no_line_crossing`, `not_counted_stationary` |
| `uncertain` | True if any uncertainty flag is set |
| `flags` | See below |
| `notes` | Human-readable explanations (merges, reasons not counted) |
| `track_ids` | Tracker IDs merged into this record |
| `first_seen_s`, `last_seen_s`, `first_frame`, `last_frame`, `n_observations` | Observation span |
| `reference_time_s`, `crossing_time_s`, `crossing_direction`, `velocity_px_per_s` | Ordering evidence |

### Flags

| Flag | Meaning | Uncertain? |
|---|---|---|
| `class_uncertain` | Class votes too split or too few | yes |
| `ambiguous_identity` | Several plausible fragment continuations; kept separate (possible over-count) | yes |
| `duplicate_candidate` | Overlaps another concurrent record without meeting the duplicate rule (possible over-count) | yes |
| `possible_id_switch` | Box centre jumped further than its motion predicts | yes |
| `sequence_extrapolated` | Reference-line time extrapolated, not observed | yes |
| `direction_inconsistent` | Moved against the dominant travel direction | yes |
| `fragment_merged` | Several sequential tracker IDs linked into this wagon | no |
| `duplicate_merged` | Concurrent duplicate tracks merged into this wagon | no |
| `partial_at_start` / `partial_at_end` | Visible near the start/end of the video; passage only partly observed | no |
| `insufficient_evidence` | Below `resolution.min_observations` / `min_duration_seconds` | n/a (not counted) |
| `stationary_object` | Not moving with the passing train (e.g. stock parked on another track); `counting.exclude_stationary` | n/a (not counted) |

## wagons.csv

Columns: `sequence_position, wagon_uid, class_name, class_confidence, class_best_guess, class_distribution,
count_status, uncertain, flags, first_seen_s, last_seen_s, reference_time_s, crossing_time_s, first_frame,
last_frame, track_ids, n_observations, notes`. Multi-valued cells use `;` (`flags`, `track_ids`),
`class_distribution` is `CLASS:share; ...`, notes are joined with ` | `.

## tracks.csv

Columns: `wagon_uid, track_id, frame_index, sample_index, timestamp_s, x1, y1, x2, y2, class_name,
confidence, touches_edge`. One row per (wagon, sampled frame), after per-frame de-duplication of merged
duplicate tracks. Boxes are ByteTrack-smoothed boxes in source-video pixels.

## Annotated video

Each box label reads `#<position> <wagon_uid> <final class>[?] <class confidence> | trk <tracker id>
(<frame-level class> <detection confidence>)`. Orange boxes with `?` are uncertain records, grey boxes are
records that were not counted, other colours are per class. The cyan line is the reference/counting line.
The header shows time, source frame index and how many counted wagons have passed the reference line.
