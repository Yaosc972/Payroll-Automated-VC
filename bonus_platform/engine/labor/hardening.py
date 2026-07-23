from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


MIB = 1024**2
GIB = 1024**3


class LaborResourceLimitError(ValueError):
    def __init__(self, code: str, message: str, *, limit: int, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.limit = int(limit)
        self.details = details or {}


class LaborTaskLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reserved: dict[str, tuple[str, str]] = {}

    @staticmethod
    def _active_metadata(active_runs: list[dict[str, Any]]) -> dict[str, str]:
        active: dict[str, str] = {}
        for metadata in active_runs:
            run_id = str(metadata.get("id") or "").strip()
            is_active = str(metadata.get("status") or "") == "抽取中"
            if run_id and is_active:
                active[run_id] = str(metadata.get("ownerUserId") or "local-default")
        return active

    def reserve(
        self,
        run_id: str,
        owner_user_id: str,
        *,
        policy: LaborHardeningPolicy,
        active_runs: list[dict[str, Any]],
    ) -> str:
        owner = str(owner_user_id or "local-default")
        with self._lock:
            if run_id in self._reserved:
                raise LaborResourceLimitError(
                    "LABOR_RUN_ALREADY_ACTIVE",
                    "当前批次已有核对任务正在运行。",
                    limit=1,
                    details={"runId": str(run_id)},
                )
            # Reservations are process-local. Metadata left by a previous process
            # cannot represent a task still executing in this process.
            active = {
                active_run_id: active_owner
                for active_run_id, (active_owner, _token) in self._reserved.items()
            }
            active.pop(run_id, None)
            owner_count = sum(active_owner == owner for active_owner in active.values())
            if owner_count >= policy.max_active_tasks_per_owner:
                raise LaborResourceLimitError(
                    "LABOR_OWNER_CONCURRENCY_LIMIT_EXCEEDED",
                    "当前用户已有海外劳务核对任务正在运行。",
                    limit=policy.max_active_tasks_per_owner,
                    details={"activeOwnerTasks": owner_count},
                )
            if len(active) >= policy.max_active_tasks_global:
                raise LaborResourceLimitError(
                    "LABOR_GLOBAL_CONCURRENCY_LIMIT_EXCEEDED",
                    "海外劳务核对任务已达到系统并发上限。",
                    limit=policy.max_active_tasks_global,
                    details={"activeGlobalTasks": len(active)},
                )
            token = uuid4().hex
            self._reserved[run_id] = (owner, token)
            return token

    def release(self, run_id: str, reservation_token: str) -> bool:
        with self._lock:
            current = self._reserved.get(run_id)
            if current is None or current[1] != str(reservation_token or ""):
                return False
            self._reserved.pop(run_id, None)
            return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            by_owner: dict[str, int] = {}
            for owner, _token in self._reserved.values():
                by_owner[owner] = by_owner.get(owner, 0) + 1
            return {
                "activeGlobalTasks": len(self._reserved),
                "activeTasksByOwner": by_owner,
            }


def _positive_env(name: str, default: int) -> int:
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _retention_env(name: str, default: int) -> int:
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        return default
    return max(value, 0)


@dataclass(frozen=True)
class LaborHardeningPolicy:
    run_retention_days: int
    ocr_cache_retention_days: int
    ocr_cache_max_bytes: int
    max_pdf_bytes: int
    max_workbook_bytes: int
    max_pdf_files: int
    max_workbook_files: int
    max_pdf_pages: int
    max_active_tasks_per_owner: int
    max_active_tasks_global: int

    @classmethod
    def from_env(cls) -> "LaborHardeningPolicy":
        return cls(
            run_retention_days=_retention_env("LABOR_RUN_RETENTION_DAYS", 90),
            ocr_cache_retention_days=_retention_env("LABOR_OCR_CACHE_RETENTION_DAYS", 30),
            ocr_cache_max_bytes=_positive_env("LABOR_OCR_CACHE_MAX_BYTES", 5 * GIB),
            max_pdf_bytes=_positive_env("LABOR_MAX_PDF_BYTES", 50 * MIB),
            max_workbook_bytes=_positive_env("LABOR_MAX_WORKBOOK_BYTES", 20 * MIB),
            max_pdf_files=_positive_env("LABOR_MAX_PDF_FILES", 30),
            max_workbook_files=_positive_env("LABOR_MAX_WORKBOOK_FILES", 10),
            max_pdf_pages=_positive_env("LABOR_MAX_PDF_PAGES", 300),
            max_active_tasks_per_owner=_positive_env("LABOR_MAX_ACTIVE_TASKS_PER_OWNER", 1),
            max_active_tasks_global=_positive_env("LABOR_MAX_ACTIVE_TASKS_GLOBAL", 2),
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def labor_storage_info(
    policy: LaborHardeningPolicy,
    *,
    run_dir: Path,
    cache_dir: Path,
    audit_path: Path,
    storage_backend: str,
    storage_environment: str,
    persistent_enabled: bool,
) -> dict[str, Any]:
    return {
        "storageBackend": str(storage_backend or "local"),
        "storageEnvironment": str(storage_environment or "local"),
        "persistentStorageEnabled": bool(persistent_enabled),
        "paths": {
            "runDirectory": str(Path(run_dir)),
            "ocrCacheDirectory": str(Path(cache_dir)),
            "auditLog": str(Path(audit_path)),
        },
        "retention": {
            "runDays": policy.run_retention_days,
            "ocrCacheDays": policy.ocr_cache_retention_days,
        },
        "limits": {
            "ocrCacheMaxBytes": policy.ocr_cache_max_bytes,
            "maxPdfBytes": policy.max_pdf_bytes,
            "maxWorkbookBytes": policy.max_workbook_bytes,
            "maxPdfFiles": policy.max_pdf_files,
            "maxWorkbookFiles": policy.max_workbook_files,
            "maxPdfPages": policy.max_pdf_pages,
            "maxActiveTasksPerOwner": policy.max_active_tasks_per_owner,
            "maxActiveTasksGlobal": policy.max_active_tasks_global,
        },
    }
