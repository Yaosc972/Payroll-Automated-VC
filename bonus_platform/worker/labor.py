from __future__ import annotations

import socket
import threading

from bonus_platform.app import _run_labor_extract_compare
from bonus_platform.engine.labor.jobs import claim_next_labor_job, complete_labor_job, fail_labor_job, heartbeat_labor_job
from bonus_platform.engine.labor.runs import get_labor_run_dir, load_labor_metadata


def process_one_labor_job(worker_id: str | None = None) -> dict | None:
    worker_name = worker_id or f"labor-worker-{socket.gethostname()}"
    job = claim_next_labor_job(worker_name)
    if not job:
        return None
    stop_heartbeat = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(str(job["id"]), worker_name, stop_heartbeat),
        name=f"labor-heartbeat-{job['id']}",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        succeeded = _run_labor_extract_compare(str(job["runId"]))
        if succeeded is False:
            raise RuntimeError(_labor_run_failure_message(str(job["runId"])))
    except Exception as exc:
        _stop_heartbeat(stop_heartbeat, heartbeat_thread)
        return fail_labor_job(str(job["id"]), str(exc), retryable=_is_retryable_worker_error(exc))
    _stop_heartbeat(stop_heartbeat, heartbeat_thread)
    return complete_labor_job(str(job["id"]))


def _heartbeat_loop(job_id: str, worker_id: str, stop: threading.Event) -> None:
    while not stop.wait(30):
        try:
            heartbeat_labor_job(job_id, worker_id)
        except Exception:
            continue


def _stop_heartbeat(stop: threading.Event, thread: threading.Thread) -> None:
    stop.set()
    thread.join(timeout=1.0)


def _labor_run_failure_message(run_id: str) -> str:
    try:
        metadata = load_labor_metadata(get_labor_run_dir(run_id))
    except Exception:
        return "劳务核对任务失败。"
    async_task = metadata.get("asyncTask") if isinstance(metadata.get("asyncTask"), dict) else {}
    return str(metadata.get("errorMessage") or async_task.get("message") or "劳务核对任务失败。")


def _is_retryable_worker_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("timeout", "timed out", "ssl", "eof", "remote end", "temporarily", "connection", "超时", "中断", "连接", "暂时"))
