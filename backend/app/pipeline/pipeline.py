"""Pipeline orchestrator: wires the stages together without containing their algorithms.

    process_video(input_path, config) -> ProcessingResult

Pass 1 decodes + samples frames, runs detection and ByteTrack, and keeps compact track
histories (no frames are retained). Wagon resolution, counting and sequencing run on the
finished histories. Pass 2 re-reads the same sampled frames to render the annotated video
with final wagon identities. The module has no web-framework dependencies; progress is
reported through an optional callback so a future worker can persist job status.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.core.exceptions import JobCancelledError, PipelineError, VideoInputError
from app.core.logging import add_file_handler, get_logger, remove_handler
from app.pipeline import exporters
from app.pipeline.config import PipelineConfig
from app.pipeline.detector import Detector, create_detector
from app.pipeline.models import ProcessingResult, ProgressCallback, ProgressEvent, WagonFlag
from app.pipeline.sequence_builder import analyze_motion, build_sequence
from app.pipeline.track_manager import TrackManager
from app.pipeline.tracker import Tracker, create_tracker
from app.pipeline.video_reader import SamplingStats, inspect_video, iter_samples, planned_sampling_rate
from app.pipeline.visualizer import FrameAnnotator, render_video
from app.pipeline.wagon_counter import apply_line_counting, apply_stationary_exclusion, calculate_counts
from app.pipeline.wagon_registry import WagonRegistry

log = get_logger("pipeline")

TrackerFactory = Callable[[PipelineConfig, float], Tracker]
CancelCheck = Callable[[], bool]


def new_run_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def _emit(cb: ProgressCallback | None, event: ProgressEvent) -> None:
    if cb is not None:
        try:
            cb(event)
        except Exception:  # a broken progress sink must never fail the job
            log.exception("Progress callback raised; ignoring")


def process_video(
    input_path: str | Path,
    config: PipelineConfig,
    *,
    run_dir: str | Path | None = None,
    run_id: str | None = None,
    progress: ProgressCallback | None = None,
    detector: Detector | None = None,
    tracker_factory: TrackerFactory | None = None,
    should_cancel: CancelCheck | None = None,
) -> ProcessingResult:
    """Process one video. Writes outputs into `run_dir` (default: <output_dir>/<run_id>).

    `detector` / `tracker_factory` allow dependency injection (tests, future model types).
    `should_cancel` is polled once per frame (detection and rendering passes); when it returns
    True, processing stops with JobCancelledError and result.json records status "cancelled".
    Raises a PipelineError subclass on failure after writing a failed result.json.
    """
    run_id = run_id or new_run_id()
    out_dir = Path(run_dir) if run_dir else config.resolved_output_dir() / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    log_handler = add_file_handler(out_dir / "run.log")
    timing: dict[str, float] = {}
    t_start = time.perf_counter()
    result = ProcessingResult(
        run_id=run_id, status="failed", video=None, model={}, config=config.model_dump(mode="json"),
        sampling={}, timing=timing, counts=None, sequence=[], sequence_info={}, wagons=[], warnings=[],
        unresolved_identities=[], artifacts={"log": "run.log"}, output_dir=str(out_dir),
    )
    result.config["resolved_model_path"] = str(config.resolved_model_path())
    try:
        _run(Path(input_path), config, out_dir, result, timing, progress, detector, tracker_factory, should_cancel)
        result.status = "completed"
    except JobCancelledError as exc:
        result.status = "cancelled"
        result.error = f"{type(exc).__name__}: {exc}"
        log.warning("Run %s cancelled: %s", run_id, exc)
        raise
    except PipelineError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        log.error("Run %s failed: %s", run_id, result.error)
        raise
    except Exception as exc:  # unexpected bug: still record a failed result
        result.error = f"Unexpected {type(exc).__name__}: {exc}"
        log.exception("Run %s failed unexpectedly", run_id)
        raise
    finally:
        timing["total"] = round(time.perf_counter() - t_start, 3)
        try:
            result.artifacts.setdefault("result_json", "result.json")
            exporters.write_json(result, out_dir / "result.json")
            (out_dir / "summary.txt").write_text(exporters.format_summary(result) + "\n", encoding="utf-8")
            result.artifacts.setdefault("summary", "summary.txt")
        except Exception:
            log.exception("Could not write final result files")
        remove_handler(log_handler)
    return result


def _run(
    input_path: Path,
    config: PipelineConfig,
    out_dir: Path,
    result: ProcessingResult,
    timing: dict[str, float],
    progress: ProgressCallback | None,
    detector: Detector | None,
    tracker_factory: TrackerFactory | None,
    should_cancel: CancelCheck | None = None,
) -> None:
    warnings = result.warnings

    def check_cancel(where: str) -> None:
        if should_cancel is not None and should_cancel():
            raise JobCancelledError(f"Cancellation requested during {where}")

    # ---- validation + model --------------------------------------------------------
    _emit(progress, ProgressEvent("validating", "Validating input video"))
    t0 = time.perf_counter()
    meta = inspect_video(input_path)
    result.video = meta
    log.info("Input %s: %dx%d, fps=%s, frames=%s, codec=%s",
             input_path.name, meta.width, meta.height, meta.fps, meta.frame_count, meta.codec)
    if meta.fps is None:
        warnings.append("Video reports no valid FPS; timestamps rely on decoder positions or a 30 fps assumption")

    _emit(progress, ProgressEvent("loading_model", "Loading detection model"))
    detector = detector or create_detector(config.detector, config.resolved_model_path())
    result.model = detector.info()
    timing["setup"] = round(time.perf_counter() - t0, 3)

    rate = planned_sampling_rate(meta.fps, config.sampling.target_fps)
    tracker = tracker_factory(config, rate) if tracker_factory else create_tracker(config.tracker, config.track, rate)
    result.config["tracker_runtime"] = tracker.info()
    manager = TrackManager(config.track, config.classes, lost_timeout_seconds=config.tracker.track_buffer_seconds)

    total_est = None
    if meta.frame_count and meta.fps:
        total_est = int(meta.frame_count * min(1.0, rate / meta.fps))
        if config.sampling.max_frames:
            total_est = min(total_est, config.sampling.max_frames)

    # ---- pass 1: detection + tracking -------------------------------------------------
    stats = SamplingStats()
    t_det = t_trk = 0.0
    n_detections = 0
    t1 = time.perf_counter()
    for sample in iter_samples(input_path, config.sampling.target_fps, meta.fps, config.sampling.max_frames, stats):
        check_cancel("detection")
        a = time.perf_counter()
        detections = detector.detect(sample.image, sample.frame_index, sample.timestamp)
        b = time.perf_counter()
        observations = tracker.update(detections, sample)
        manager.update(observations, sample)
        c = time.perf_counter()
        t_det += b - a
        t_trk += c - b
        n_detections += len(detections)
        if sample.sample_index % 25 == 0:
            _emit(progress, ProgressEvent(
                "detecting_and_tracking", f"Frame {sample.frame_index} (t={sample.timestamp:.2f}s)",
                stats.sampled_frames, total_est,
            ))
    timing["pass1_detect_track"] = round(time.perf_counter() - t1, 3)
    timing["inference"] = round(t_det, 3)
    timing["tracking"] = round(t_trk, 3)
    if stats.sampled_frames == 0:
        raise VideoInputError("No frames could be sampled from the video")
    result.sampling = {**stats.to_dict(), "detections_total": n_detections}
    if stats.timestamp_fallbacks:
        warnings.append(f"{stats.timestamp_fallbacks} frame timestamps were derived from frame index (decoder times invalid)")
    if meta.frame_count and abs(stats.decoded_frames - meta.frame_count) > max(2, 0.02 * meta.frame_count) and not stats.stopped_early:
        warnings.append(f"Container reported {meta.frame_count} frames but {stats.decoded_frames} were decoded")
    if n_detections == 0:
        warnings.append("The detector produced no detections in any sampled frame")
    log.info("Pass 1: %d/%d frames sampled, %d detections, %d tracker IDs (%.1fs)",
             stats.sampled_frames, stats.decoded_frames, n_detections, len(manager.tracks),
             timing["pass1_detect_track"])

    # ---- resolution, counting, sequencing ------------------------------------------------
    _emit(progress, ProgressEvent("resolving", "Resolving wagon identities", stats.sampled_frames, total_est))
    t2 = time.perf_counter()
    tracks = manager.finalize()
    registry = WagonRegistry(config.resolution, config.track, config.classes, config.counting)
    reg = registry.resolve(tracks, frame_size=(meta.width, meta.height))
    warnings.extend(reg.warnings)
    result.unresolved_identities = reg.unresolved

    motion = analyze_motion(
        reg.wagons, reg.observations, (meta.width, meta.height), config.counting, config.resolution,
        video_span=(stats.first_timestamp, stats.last_timestamp), edge_margin=config.track.edge_margin_px,
    )
    if config.counting.exclude_stationary:
        apply_stationary_exclusion(reg.wagons)
        n_stationary = sum(1 for w in reg.wagons if w.count_status.value == "not_counted_stationary")
        if n_stationary:
            warnings.append(f"{n_stationary} record(s) were not moving with the train and were not counted "
                            "(e.g. stock on another track); see wagon flags 'stationary_object'")
    if config.counting.mode == "line":
        if motion.direction == 0:
            warnings.append("Line counting requested but no consistent travel direction was found; nothing crossed the line")
        apply_line_counting(reg.wagons)
    counts = calculate_counts(reg.wagons, config.counting, tracker_ids_seen=len(tracks))
    sequence, seq_info = build_sequence(reg.wagons, reg.observations, motion, config.counting)
    result.wagons, result.counts, result.sequence, result.sequence_info = reg.wagons, counts, sequence, seq_info
    timing["resolution"] = round(time.perf_counter() - t2, 3)

    n_unresolved_class = sum(1 for w in reg.wagons if w.counted and WagonFlag.CLASS_UNCERTAIN in w.flags)
    if n_unresolved_class:
        warnings.append(f"{n_unresolved_class} counted wagon(s) have an unresolved class ('{config.classes.unresolved_label}')")
    if motion.inconsistent_wagons:
        warnings.append(f"{len(motion.inconsistent_wagons)} wagon(s) moved against the dominant direction")
    if seq_info["completeness"] in ("partial_start", "partial_end", "partial_both"):
        warnings.append(f"Sequence completeness is '{seq_info['completeness']}': the train may extend beyond the video")

    # ---- exports + pass 2 rendering ----------------------------------------------------------
    t3 = time.perf_counter()
    if config.output.save_tracks_csv:
        exporters.write_tracks_csv(reg.observations, out_dir / "tracks.csv")
        result.artifacts["tracks_csv"] = "tracks.csv"
    result.artifacts["wagons_csv"] = "wagons.csv"
    exporters.write_wagons_csv(result, out_dir / "wagons.csv")
    timing["export"] = round(time.perf_counter() - t3, 3)

    if config.output.write_video:
        _emit(progress, ProgressEvent("rendering", "Rendering annotated video", 0, stats.sampled_frames))
        t4 = time.perf_counter()
        annotator = FrameAnnotator(reg.wagons, reg.observations, motion, config.output.draw_counting_line)
        render_stats = SamplingStats()

        def on_rendered(n: int) -> None:
            check_cancel("rendering")
            if n % 25 == 0:
                _emit(progress, ProgressEvent("rendering", f"Rendered {n} frames", n, stats.sampled_frames))

        codec, written = render_video(
            iter_samples(input_path, config.sampling.target_fps, meta.fps, config.sampling.max_frames, render_stats),
            annotator,
            out_dir / "annotated.mp4",
            fps=stats.effective_fps,
            size=(meta.width, meta.height),
            codecs=config.output.video_codecs,
            on_frame=on_rendered,
        )
        result.artifacts["annotated_video"] = "annotated.mp4"
        result.sampling["output_video"] = {"codec": codec, "fps": round(stats.effective_fps, 4), "frames": written}
        if written != stats.sampled_frames:
            warnings.append(f"Annotated video has {written} frames but pass 1 sampled {stats.sampled_frames}")
        if codec.lower() not in ("avc1", "h264"):
            warnings.append(f"Annotated video uses codec '{codec}', which most web browsers cannot play; "
                            "transcode to H.264 for website playback")
        timing["render"] = round(time.perf_counter() - t4, 3)

    _emit(progress, ProgressEvent("completed", "Processing complete", stats.sampled_frames, stats.sampled_frames))
