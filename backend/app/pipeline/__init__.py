"""Core computer-vision pipeline. Must not import web frameworks (FastAPI, etc.)."""

from app.pipeline.config import PipelineConfig, load_config
from app.pipeline.models import ProcessingResult, ProgressEvent


def process_video(*args, **kwargs) -> ProcessingResult:
    """Lazy wrapper so importing the package does not pull in OpenCV/Ultralytics eagerly."""
    from app.pipeline.pipeline import process_video as _process_video

    return _process_video(*args, **kwargs)


__all__ = ["PipelineConfig", "ProcessingResult", "ProgressEvent", "load_config", "process_video"]
