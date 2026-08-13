from __future__ import annotations

from datetime import datetime
from typing import Any

from ...time_utils import utcnow_naive


def build_labor_operations_snapshot(
    jobs: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    storage: dict[str, Any],
) -> dict[str, Any]:
    now = utcnow_naive()
    alerts: list[dict[str, Any]] = []
    active = [job for job in jobs if job.get("status") in {"queued", "running", "retry_wait"}]
    stale_running = [
        job for job in active
        if job.get("status") == "running" and _age_seconds(job.get("heartbeatAt"), now) > 300
    ]
    waiting_without_worker = [
        job for job in active
        if job.get("status") in {"queued", "retry_wait"} and _age_seconds(job.get("availableAt") or job.get("createdAt"), now) > 300
    ]
    if stale_running or waiting_without_worker:
        count = len(stale_running) + len(waiting_without_worker)
        alerts.append(_alert("WORKER_OFFLINE", "critical", f"{count} 个任务超过 5 分钟未获得有效 Worker 心跳。"))

    over_30 = [
        job for job in active
        if job.get("status") == "running" and _age_seconds(job.get("startedAt"), now) > 1800
    ]
    if over_30:
        alerts.append(_alert("TASK_OVER_30_MINUTES", "warning", f"{len(over_30)} 个任务已运行超过 30 分钟。"))

    ocr_failures = [job for job in jobs if job.get("status") == "failed" and "OCR" in str(job.get("errorCode") or "").upper()]
    if ocr_failures:
        alerts.append(_alert("OCR_FAILURE", "warning", f"{len(ocr_failures)} 个任务因 OCR 失败终止。"))

    free_bytes = int(storage.get("freeBytes") or 0)
    minimum_free = int(storage.get("minimumFreeBytes") or 0)
    low_worker_storage = []
    for job in active:
        progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
        worker_storage = progress.get("storage") if isinstance(progress.get("storage"), dict) else {}
        worker_free = int(worker_storage.get("freeBytes") or 0)
        worker_minimum = int(worker_storage.get("minimumFreeBytes") or 0)
        if worker_minimum and worker_free < worker_minimum:
            low_worker_storage.append(job)
    if (minimum_free and free_bytes < minimum_free) or low_worker_storage:
        alerts.append(_alert("STORAGE_CAPACITY_LOW", "critical", "可用存储容量低于安全阈值。"))

    terminal = [job for job in jobs if job.get("status") in {"succeeded", "failed"}]
    durations = [
        duration
        for duration in (_duration_seconds(job.get("startedAt"), job.get("finishedAt")) for job in terminal)
        if duration is not None
    ]
    cache_events = [event for event in events if event.get("event") == "ocr_cache"]
    cache_hits = sum(1 for event in cache_events if (event.get("summary") or {}).get("cacheHit") is True)
    model_events = [event for event in events if event.get("event") == "model_call"]
    model_failures = sum(1 for event in model_events if event.get("status") == "failed")
    failed = sum(1 for job in terminal if job.get("status") == "failed")

    return {
        "generatedAt": now.isoformat(timespec="seconds") + "Z",
        "alerts": alerts,
        "metrics": {
            "totalJobs": len(jobs),
            "activeJobs": len(active),
            "failedJobs": failed,
            "taskFailureRate": _ratio(failed, len(terminal)),
            "averageDurationSeconds": round(sum(durations) / len(durations)) if durations else 0,
            "ocrCacheHitRate": _ratio(cache_hits, len(cache_events)),
            "modelCallFailureRate": _ratio(model_failures, len(model_events)),
        },
        "recentJobs": sorted(jobs, key=lambda row: str(row.get("updatedAt") or row.get("createdAt") or ""), reverse=True)[:50],
        "storage": dict(storage),
    }


def _alert(code: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or "").removesuffix("Z"))
    except (TypeError, ValueError):
        return None


def _age_seconds(value: Any, now: datetime) -> float:
    parsed = _parse_time(value)
    return (now - parsed).total_seconds() if parsed else float("inf")


def _duration_seconds(start: Any, finish: Any) -> float | None:
    started = _parse_time(start)
    finished = _parse_time(finish)
    if not started or not finished:
        return None
    return max(0, (finished - started).total_seconds())


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0
