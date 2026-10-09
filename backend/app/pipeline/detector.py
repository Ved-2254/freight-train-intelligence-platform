"""Object-detector interface and the Ultralytics YOLO adapter.

Only this module imports Ultralytics for detection. Downstream stages consume project-owned
`Detection` objects, so the model/library can be replaced without touching tracking code.
Class names always come from the loaded model, never from a hardcoded list.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from app.core.exceptions import InferenceError, ModelClassMismatchError, ModelLoadError
from app.core.logging import get_logger
from app.pipeline.config import DetectorConfig
from app.pipeline.geometry import clip_box
from app.pipeline.models import Detection

log = get_logger("detector")


class Detector(Protocol):
    class_names: dict[int, str]

    def detect(self, image: np.ndarray, frame_index: int, timestamp: float) -> list[Detection]: ...

    def info(self) -> dict[str, Any]: ...


def normalize_detections(
    xyxy: np.ndarray,
    confidences: np.ndarray,
    class_ids: np.ndarray,
    class_names: dict[int, str],
    frame_index: int,
    timestamp: float,
    frame_width: int,
    frame_height: int,
    min_box_size: float = 1.0,
) -> list[Detection]:
    """Convert raw detector arrays into Detection objects (clipped; boxes below min size dropped)."""
    out: list[Detection] = []
    xyxy = np.asarray(xyxy, dtype=float).reshape(-1, 4)
    confidences = np.asarray(confidences, dtype=float).reshape(-1)
    class_ids = np.asarray(class_ids).reshape(-1).astype(int)
    if not (len(xyxy) == len(confidences) == len(class_ids)):
        raise InferenceError("Detector returned arrays of mismatched length")
    for box, conf, cid in zip(xyxy, confidences, class_ids):
        b = clip_box(box, frame_width, frame_height)
        if b[2] - b[0] < min_box_size or b[3] - b[1] < min_box_size:
            continue
        name = class_names.get(int(cid))
        if name is None:
            raise InferenceError(f"Detector returned class id {cid} not present in the model's class map")
        out.append(Detection(b, int(cid), name, float(conf), frame_index, timestamp))
    return out


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while data := f.read(chunk):
            h.update(data)
    return h.hexdigest()


def resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        return "0" if torch.cuda.is_available() else "cpu"
    except Exception:  # torch missing or broken CUDA setup
        return "cpu"


class UltralyticsDetector:
    """Adapter for Ultralytics YOLO detection checkpoints (.pt)."""

    def __init__(self, cfg: DetectorConfig, model_path: Path):
        self.cfg = cfg
        self.model_path = Path(model_path)
        if not self.model_path.is_file():
            raise ModelLoadError(f"Model weights not found: {self.model_path}")
        if self.model_path.suffix.lower() != ".pt":
            raise ModelLoadError(
                f"Unsupported model file extension '{self.model_path.suffix}' for {self.model_path.name}; "
                "the Ultralytics adapter expects a PyTorch '.pt' checkpoint"
            )
        try:
            import ultralytics
            from ultralytics import YOLO
        except ImportError as exc:
            raise ModelLoadError(f"Ultralytics is not installed or failed to import: {exc}") from exc

        self.framework_version = ultralytics.__version__
        self.device = resolve_device(cfg.device)
        self._precision_kwargs = self._precision_args(cfg.half)
        try:
            self.model = YOLO(str(self.model_path), task="detect")
        except Exception as exc:
            raise ModelLoadError(f"Failed to load {self.model_path.name} with Ultralytics {self.framework_version}: {exc}") from exc
        if getattr(self.model, "task", "detect") != "detect":
            raise ModelLoadError(f"Model task is '{self.model.task}', expected 'detect'")

        names = self.model.names
        self.class_names = {int(k): str(v) for k, v in (names.items() if isinstance(names, dict) else enumerate(names))}
        if not self.class_names:
            raise ModelLoadError("Loaded model exposes no class names")
        if cfg.expected_classes is not None:
            actual = [self.class_names[k] for k in sorted(self.class_names)]
            if actual != list(cfg.expected_classes):
                raise ModelClassMismatchError(
                    f"Model classes {actual} do not match configured expected_classes {cfg.expected_classes}"
                )
        self.sha256 = file_sha256(self.model_path)
        self.metadata = self._checkpoint_metadata()
        log.info("Loaded %s (sha256 %s..., %d classes) on device %s",
                 self.model_path.name, self.sha256[:12], len(self.class_names), self.device)

    @staticmethod
    def _precision_args(half: bool) -> dict[str, Any]:
        """FP16 flag for the installed Ultralytics: newer versions replaced `half` with `quantize`."""
        if not half:
            return {}
        try:
            from ultralytics.cfg import DEFAULT_CFG_DICT

            if "quantize" in DEFAULT_CFG_DICT:
                return {"quantize": 16}
        except ImportError:
            pass
        return {"half": True}

    def _checkpoint_metadata(self) -> dict[str, Any]:
        ckpt = getattr(self.model, "ckpt", None) or {}
        meta: dict[str, Any] = {}
        for key in ("date", "version"):
            if key in ckpt:
                meta[f"trained_{key}"] = str(ckpt[key])
        args = ckpt.get("train_args") or {}
        for key in ("model", "imgsz", "epochs", "name"):
            if key in args:
                meta[f"train_{key}"] = str(args[key]) if not isinstance(args[key], (int, float)) else args[key]
        metrics = ckpt.get("train_metrics") or {}
        for key in ("metrics/precision(B)", "metrics/recall(B)", "metrics/mAP50(B)", "metrics/mAP50-95(B)"):
            if key in metrics:
                meta[key] = round(float(metrics[key]), 4)
        return meta

    def detect(self, image: np.ndarray, frame_index: int, timestamp: float) -> list[Detection]:
        try:
            results = self.model.predict(
                image,
                conf=self.cfg.confidence_threshold,
                iou=self.cfg.iou_threshold,
                imgsz=self.cfg.image_size,
                device=self.device,
                **self._precision_kwargs,
                agnostic_nms=self.cfg.agnostic_nms,
                max_det=self.cfg.max_det,
                verbose=False,
            )
        except Exception as exc:
            raise InferenceError(f"Inference failed on frame {frame_index} (t={timestamp:.3f}s): {exc}") from exc
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return []
        h, w = image.shape[:2]
        return normalize_detections(
            boxes.xyxy.cpu().numpy(),
            boxes.conf.cpu().numpy(),
            boxes.cls.cpu().numpy(),
            self.class_names,
            frame_index,
            timestamp,
            w,
            h,
            min_box_size=self.cfg.min_box_size_px,
        )

    def info(self) -> dict[str, Any]:
        return {
            "adapter": "ultralytics",
            "framework_version": self.framework_version,
            "model_file": self.model_path.name,
            "model_path": str(self.model_path),
            "sha256": self.sha256,
            "device": self.device,
            "class_names": {str(k): v for k, v in sorted(self.class_names.items())},
            "num_classes": len(self.class_names),
            "checkpoint": self.metadata,
        }


def create_detector(cfg: DetectorConfig, model_path: Path) -> UltralyticsDetector:
    return UltralyticsDetector(cfg, model_path)
