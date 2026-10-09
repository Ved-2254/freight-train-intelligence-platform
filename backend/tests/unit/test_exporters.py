import csv
import json
from pathlib import Path

from app.pipeline import exporters
from app.pipeline.config import ClassConfig, CountingConfig, ResolutionConfig, TrackConfig
from app.pipeline.models import ProcessingResult, VideoMetadata
from app.pipeline.sequence_builder import analyze_motion, build_sequence
from app.pipeline.wagon_counter import calculate_counts
from app.pipeline.wagon_registry import WagonRegistry
from tests.synthetic import make_track, moving_boxes


def _result(tmp_path: Path) -> tuple[ProcessingResult, dict]:
    tracks = [make_track(1, 0, moving_boxes(100, 30, 20.0), "BOXN"),
              make_track(2, 0, moving_boxes(-70, 30, 20.0), "BCN"),
              make_track(3, 50, moving_boxes(0, 2, 20.0), "BCN")]  # short, isolated
    counting = CountingConfig(boundary_seconds=0.0)
    reg = WagonRegistry(ResolutionConfig(), TrackConfig(), ClassConfig(), counting).resolve(tracks, (640, 360))
    motion = analyze_motion(reg.wagons, reg.observations, (640, 360), counting, ResolutionConfig())
    counts = calculate_counts(reg.wagons, counting, 3)
    seq, info = build_sequence(reg.wagons, reg.observations, motion, counting)
    video = VideoMetadata("x.mp4", 640, 360, 10.0, 30, 3.0, "mp4v", 1234)
    res = ProcessingResult("run1", "completed", video, {"model_file": "m.pt"}, {}, {}, {"total": 1.0},
                           counts, seq, info, reg.wagons, ["w"], reg.unresolved,
                           {"wagons_csv": "wagons.csv"}, str(tmp_path))
    return res, reg.observations


def test_json_schema_and_consistency(tmp_path: Path):
    res, _ = _result(tmp_path)
    exporters.write_json(res, tmp_path / "result.json")
    data = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    for key in ("schema_version", "run_id", "status", "input", "model", "config", "sampling", "timing_seconds",
                "counts", "sequence_info", "sequence", "wagons", "warnings", "unresolved_identities", "artifacts"):
        assert key in data
    assert data["counts"]["total_counted"] == len(data["sequence"]) == 2
    assert sum(data["counts"]["type_counts"].values()) == data["counts"]["total_counted"]
    assert len(data["wagons"]) == 3  # not-counted record is still reported
    assert data["wagons"][-1]["count_status"] == "not_counted_insufficient_evidence"
    assert [s["position"] for s in data["sequence"]] == [1, 2]
    all_tracks = sorted(t for w in data["wagons"] for t in w["track_ids"])
    assert all_tracks == [1, 2, 3]  # every tracker id maps to exactly one wagon


def test_wagons_csv_has_expected_columns_and_rows(tmp_path: Path):
    res, obs = _result(tmp_path)
    exporters.write_wagons_csv(res, tmp_path / "wagons.csv")
    exporters.write_tracks_csv(obs, tmp_path / "tracks.csv")
    with (tmp_path / "wagons.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == exporters.WAGON_CSV_COLUMNS
    assert [r["sequence_position"] for r in rows] == ["1", "2", ""]
    assert rows[0]["class_name"] == "BOXN"
    with (tmp_path / "tracks.csv").open(encoding="utf-8") as f:
        assert len(list(csv.reader(f))) == 1 + 30 + 30 + 2


def test_summary_mentions_counts(tmp_path: Path):
    res, _ = _result(tmp_path)
    text = exporters.format_summary(res)
    assert "Total wagons: 2" in text and "BOXN" in text
