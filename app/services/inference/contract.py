"""Stable inference progress + error contract."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Progress:
    percent: int
    stage: str = "running"
    message: str | None = None

    def clamp(self) -> "Progress":
        return Progress(
            percent=max(0, min(100, int(self.percent))),
            stage=self.stage,
            message=self.message,
        )


# Canonical error codes surfaced to the UI / admin views.
ERROR_INVALID_INPUT = "invalid_input"
ERROR_MODEL_LOAD_FAILED = "model_load_failed"
ERROR_OOM = "oom"
ERROR_TIMEOUT = "timeout"
ERROR_TRANSIENT_STORAGE = "transient_storage"
ERROR_CANCELLED = "cancelled"
ERROR_UNKNOWN = "unknown"


class InferenceError(Exception):
    """Inference exception that carries a stable code for the UI."""

    code: str = ERROR_UNKNOWN

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class InvalidInputError(InferenceError):
    code = ERROR_INVALID_INPUT


class ModelLoadError(InferenceError):
    code = ERROR_MODEL_LOAD_FAILED


class TransientStorageError(InferenceError):
    code = ERROR_TRANSIENT_STORAGE


def classify_exception(exc: BaseException) -> str:
    """Best-effort mapping from a raw exception to one of our error codes."""
    if isinstance(exc, InferenceError):
        return exc.code
    text = (str(exc) or "").lower()
    if "out of memory" in text or "oom" in text or "cuda out" in text:
        return ERROR_OOM
    if "timeout" in text or "timed out" in text:
        return ERROR_TIMEOUT
    if "no such file" in text or "permission" in text or "i/o error" in text:
        return ERROR_TRANSIENT_STORAGE
    if "model" in text and ("load" in text or "weights" in text):
        return ERROR_MODEL_LOAD_FAILED
    return ERROR_UNKNOWN
