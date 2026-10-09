"""Typed errors raised by the pipeline. Each maps to a CLI exit code."""


class PipelineError(Exception):
    """Base class for all expected pipeline failures."""

    exit_code = 1


class ConfigError(PipelineError):
    exit_code = 2


class VideoInputError(PipelineError):
    """Input video missing, unreadable, corrupt or empty."""

    exit_code = 2


class ModelLoadError(PipelineError):
    """Model weights missing, unloadable, or incompatible with the installed framework."""

    exit_code = 3


class ModelClassMismatchError(ModelLoadError):
    """Model class names differ from the configured `expected_classes`."""


class InferenceError(PipelineError):
    exit_code = 4


class TrackingError(PipelineError):
    exit_code = 4


class OutputWriteError(PipelineError):
    exit_code = 4


class JobCancelledError(PipelineError):
    """Processing stopped because cancellation was requested (cooperative, checked per frame)."""

    exit_code = 5
