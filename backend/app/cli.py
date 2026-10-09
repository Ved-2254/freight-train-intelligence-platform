"""Command-line entry point (run from the `backend/` directory).

    python -m app.cli process --input ../data/uploads/train.mp4
    python -m app.cli process --input video.mp4 --model models/best.pt --target-fps 15 --counting-mode line
    python -m app.cli inspect-model [--model models/best.pt]

Paths given on the command line are relative to the current directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.core.exceptions import PipelineError
from app.core.logging import configure_logging, get_logger
from app.pipeline.config import load_config
from app.pipeline.models import ProgressEvent

log = get_logger("cli")


def _abs(p: str | None) -> str | None:
    return str(Path(p).expanduser().resolve()) if p else None


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="YAML config file (default: backend/configs/default.yaml)")
    parser.add_argument("--model", help="Path to model weights (.pt); overrides detector.model_path")
    parser.add_argument("--device", help="auto | cpu | 0 | cuda:0 ...")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Freight wagon video analysis")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("process", help="Process one video")
    _common(p)
    p.add_argument("--input", "-i", required=True, help="Input video file")
    p.add_argument("--output-dir", help="Parent directory for run folders (default: data/outputs)")
    p.add_argument("--run-dir", help="Exact output folder for this run (overrides --output-dir/<run_id>)")
    p.add_argument("--target-fps", type=float, help="Analysis sampling cadence (never upsamples)")
    p.add_argument("--max-frames", type=int, help="Stop after N sampled frames (quick tests)")
    p.add_argument("--conf", type=float, help="Detector confidence threshold")
    p.add_argument("--iou", type=float, help="Detector NMS IoU threshold")
    p.add_argument("--imgsz", type=int, help="Inference image size")
    p.add_argument("--track-buffer", type=float, help="ByteTrack lost-track buffer in seconds")
    p.add_argument("--counting-mode", choices=["registry", "line"])
    p.add_argument("--line-position", type=float, help="Reference/counting line as a fraction of the travel axis")
    p.add_argument("--travel-axis", choices=["auto", "x", "y"])
    p.add_argument("--no-video", action="store_true", help="Skip the annotated video")
    p.add_argument("--quiet", action="store_true", help="Do not print progress lines")

    m = sub.add_parser("inspect-model", help="Load the model and print its class map and metadata")
    _common(m)

    db = sub.add_parser("init-db", help="Create the API storage folders and SQLite database (idempotent)")
    db.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def _overrides(args: argparse.Namespace) -> dict:
    o = {
        "detector.model_path": _abs(args.model),
        "detector.device": args.device,
        "log_level": args.log_level,
    }
    if args.command == "process":
        o.update({
            "output.output_dir": _abs(args.output_dir),
            "sampling.target_fps": args.target_fps,
            "sampling.max_frames": args.max_frames,
            "detector.confidence_threshold": args.conf,
            "detector.iou_threshold": args.iou,
            "detector.image_size": args.imgsz,
            "tracker.track_buffer_seconds": args.track_buffer,
            "counting.mode": args.counting_mode,
            "counting.line_position": args.line_position,
            "counting.travel_axis": args.travel_axis,
            "output.write_video": False if args.no_video else None,
        })
    return o


def _print_progress(event: ProgressEvent) -> None:
    pct = f"{event.percent:5.1f}%" if event.percent is not None else "   ?  "
    print(f"[{pct}] {event.stage}: {event.message}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level or "INFO")
    if args.command == "init-db":
        from app.core.settings import get_settings
        from app.repositories.database import Database
        from app.storage.file_storage import LocalFileStorage

        settings = get_settings()
        LocalFileStorage(settings.storage_root).initialize()
        Database(settings.db_path).initialize()
        print(f"Initialised storage and database under {settings.storage_root}")
        return 0
    try:
        config = load_config(args.config, _overrides(args))
        configure_logging(config.log_level)

        if args.command == "inspect-model":
            from app.pipeline.detector import create_detector

            det = create_detector(config.detector, config.resolved_model_path())
            print(json.dumps(det.info(), indent=2))
            return 0

        from app.pipeline.exporters import format_summary
        from app.pipeline.pipeline import process_video

        result = process_video(
            _abs(args.input),
            config,
            run_dir=_abs(args.run_dir),
            progress=None if args.quiet else _print_progress,
        )
        print()
        print(format_summary(result))
        return 0
    except PipelineError as exc:
        log.error("%s: %s", type(exc).__name__, exc)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
