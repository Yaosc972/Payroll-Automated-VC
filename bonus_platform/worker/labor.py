from __future__ import annotations

import socket

from bonus_platform.app import _run_labor_extract_compare
from bonus_platform.engine.labor.jobs import claim_next_labor_job, complete_labor_job, fail_labor_job


def process_one_labor_job(worker_id: str | None = None) -> dict | None:
    worker_name = worker_id or f"labor-worker-{socket.gethostname()}"
    job = claim_next_labor_job(worker_name)
    if not job:
        return None
    try:
        _run_labor_extract_compare(str(job["runId"]))
    except Exception as exc:
        return fail_labor_job(str(job["id"]), str(exc), retryable=_is_retryable_worker_error(exc))
    return complete_labor_job(str(job["id"]))


def _is_retryable_worker_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("timeout", "ssl", "remote end", "temporarily", "connection"))

