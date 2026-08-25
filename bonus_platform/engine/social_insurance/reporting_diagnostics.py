from __future__ import annotations

from contextlib import contextmanager
import time
from typing import Iterator

import httpx


class ReportingRefreshDiagnostics:
    """Collect fixed, non-sensitive stage telemetry for one reporting refresh."""

    def __init__(self) -> None:
        self._started_at = time.monotonic()
        self._failed_stage = ""
        self._stage_timings_ms: dict[str, int] = {}
        self._active_stage = ""
        self._active_stage_started_at: float | None = None

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((time.monotonic() - started_at) * 1000))

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        self.begin_stage(name)
        try:
            yield
        except Exception:
            self.fail_active_stage()
            raise
        else:
            self.complete_active_stage()

    def begin_stage(self, name: str) -> None:
        if self._active_stage:
            raise RuntimeError("reporting refresh diagnostic stages cannot overlap")
        self._active_stage = name
        self._active_stage_started_at = time.monotonic()

    def complete_active_stage(self) -> None:
        if not self._active_stage or self._active_stage_started_at is None:
            return
        self._stage_timings_ms[self._active_stage] = self._elapsed_ms(
            self._active_stage_started_at
        )
        self._active_stage = ""
        self._active_stage_started_at = None

    def fail_active_stage(self) -> None:
        if self._active_stage and not self._failed_stage:
            self._failed_stage = self._active_stage
        self.complete_active_stage()

    def success_payload(self) -> dict[str, object]:
        return {
            "stageTimingsMs": dict(self._stage_timings_ms),
            "elapsedMs": self._elapsed_ms(self._started_at),
        }

    def error_payload(self, category: str) -> dict[str, object]:
        return {
            "failedStage": self._failed_stage or "unknown",
            "errorCategory": category,
            "stageTimingsMs": dict(self._stage_timings_ms),
            "elapsedMs": self._elapsed_ms(self._started_at),
        }


def safe_error_category(exc: Exception) -> str:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__

    for error in chain:
        code = str(getattr(error, "code", "") or "")
        if code == "LABOR_BLOB_TIMEOUT":
            return "storage_timeout"
        if code == "LABOR_BLOB_PERMISSION_DENIED":
            return "storage_permission"
        if code.startswith("LABOR_BLOB_"):
            return "storage_error"
    if any(error.__class__.__name__ == "SocialInsuranceStorageError" for error in chain):
        return "storage_error"
    for error in chain:
        if isinstance(error, httpx.TimeoutException):
            return "connector_timeout"
        if isinstance(error, (httpx.RequestError, httpx.HTTPStatusError)):
            return "connector_error"
        if error.__class__.__name__ == "TimeoutExpired":
            return "connector_timeout"
    if any(isinstance(error, TimeoutError) for error in chain):
        return "timeout"
    if any(isinstance(error, OSError) for error in chain):
        return "filesystem_error"
    if any(error.__class__.__name__ == "RunValidationError" for error in chain):
        return "validation"
    return "unknown"
