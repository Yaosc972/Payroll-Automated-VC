from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from ...config import OUTPUT_DIR
from .worker_jobs_postgres import PostgresLaborWorkerStore
from .worker_version import worker_version_at_least


LABOR_WORKER_JOBS_DIR = OUTPUT_DIR / "labor_worker_jobs"
ACTIVE_STATUSES = {"queued", "running", "retry_wait"}
SUPPORTED_JOB_TYPES = {"reconcile", "mapping_preflight"}
DEFAULT_LEASE_SECONDS = 120
_STORE_LOCK = threading.RLock()


class LaborWorkerLeaseError(RuntimeError):
    pass


def enqueue_labor_worker_job(
    run_id: str,
    *,
    owner_user_id: str,
    required_worker_version: str = "",
    max_attempts: int = 3,
    task_generation_id: str = "",
    job_type: str = "reconcile",
) -> dict[str, Any]:
    owner = _required_identity(owner_user_id, "owner_user_id")
    generation = str(task_generation_id or "").strip()
    normalized_job_type = _required_job_type(job_type)
    store = _postgres_store()
    if store:
        try:
            return store.enqueue(
                run_id,
                owner,
                required_worker_version,
                max_attempts,
                generation,
                normalized_job_type,
            )
        except PermissionError as exc:
            raise LaborWorkerLeaseError(str(exc)) from exc
    with _STORE_LOCK:
        for job in list_labor_worker_jobs():
            if job.get("runId") == run_id and job.get("status") in ACTIVE_STATUSES:
                if job.get("ownerUserId") != owner:
                    raise LaborWorkerLeaseError("批次任务归属与当前用户不一致。")
                active_generation = str(job.get("taskGenerationId") or "").strip()
                active_job_type = str(job.get("jobType") or "reconcile")
                if active_generation != generation or active_job_type != normalized_job_type:
                    if active_generation and not generation:
                        raise LaborWorkerLeaseError("当前批次已绑定新的任务代次，不能复用无代次 Worker 任务。")
                    _supersede_local_job(job)
                    continue
                if (
                    required_worker_version
                    and job.get("status") in {"queued", "retry_wait"}
                    and not worker_version_at_least(job.get("requiredWorkerVersion"), required_worker_version)
                ):
                    job["requiredWorkerVersion"] = str(required_worker_version)
                    job["updatedAt"] = _utc_now()
                    _write_labor_worker_job(job)
                return job
        now = _utc_now()
        job = {
            "id": f"labor_job_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}_{uuid4().hex[:8]}",
            "runId": str(run_id),
            "jobType": normalized_job_type,
            "ownerUserId": owner,
            "status": "queued",
            "attempt": 0,
            "maxAttempts": max(1, int(max_attempts)),
            "availableAt": now,
            "claimedDeviceId": "",
            "leaseExpiresAt": "",
            "heartbeatAt": "",
            "requiredWorkerVersion": str(required_worker_version),
            "taskGenerationId": generation,
            "progress": {},
            "resultAcceptedAt": "",
            "resultAcceptedGenerationId": "",
            "resultAcceptedReportSha256": "",
            "resultAcceptedReportSizeBytes": 0,
            "resultAcceptedInputFingerprint": "",
            "errorCode": "",
            "errorMessage": "",
            "createdAt": now,
            "updatedAt": now,
            "startedAt": "",
            "finishedAt": "",
        }
        _write_labor_worker_job(job)
        return job


def complete_labor_worker_preflight_job(
    job_id: str,
    *,
    owner_user_id: str,
    device_id: str,
    expected_task_generation_id: str = "",
) -> dict[str, Any]:
    """Complete a mapping preflight without weakening reconcile evidence gates."""

    store = _postgres_store()
    if store:
        try:
            return store.complete_preflight(
                job_id,
                owner_user_id,
                device_id,
                expected_task_generation_id,
            )
        except PermissionError as exc:
            raise LaborWorkerLeaseError(str(exc)) from exc
    with _STORE_LOCK:
        existing = get_labor_worker_job(job_id)
        if str(existing.get("jobType") or "reconcile") != "mapping_preflight":
            raise LaborWorkerLeaseError("正式核对任务不能使用字段预检完成通道。")
        if existing.get("status") == "succeeded":
            if existing.get("ownerUserId") != owner_user_id or existing.get("claimedDeviceId") != device_id:
                raise LaborWorkerLeaseError("任务不属于当前 Worker。")
            _assert_job_generation(existing, expected_task_generation_id)
            return existing
        job = _assert_lease(
            job_id,
            owner_user_id,
            device_id,
            expected_task_generation_id=expected_task_generation_id,
        )
        if str(job.get("jobType") or "reconcile") != "mapping_preflight":
            raise LaborWorkerLeaseError("正式核对任务不能使用字段预检完成通道。")
        job.update(
            {
                "status": "succeeded",
                "finishedAt": _utc_now(),
                "updatedAt": _utc_now(),
                "leaseExpiresAt": "",
            }
        )
        _write_labor_worker_job(job)
        return job


def claim_labor_worker_job(*, owner_user_id: str, device_id: str, worker_version: str = "") -> dict[str, Any] | None:
    owner = _required_identity(owner_user_id, "owner_user_id")
    device = _required_identity(device_id, "device_id")
    store = _postgres_store()
    if store:
        return store.claim(owner, device, worker_version)
    now = datetime.utcnow()
    with _STORE_LOCK:
        for job in list_labor_worker_jobs():
            if job.get("ownerUserId") != owner:
                continue
            status = str(job.get("status") or "")
            available = status in {"queued", "retry_wait"} and _parse_time(job.get("availableAt"), default=now) <= now
            expired = status == "running" and _parse_time(job.get("leaseExpiresAt"), default=now) <= now
            if not available and not expired:
                continue
            required = str(job.get("requiredWorkerVersion") or "")
            if required and not worker_version_at_least(worker_version, required):
                continue
            claimed = dict(job)
            claimed.update(
                {
                    "status": "running",
                    "claimedDeviceId": device,
                    "attempt": int(claimed.get("attempt") or 0) + 1,
                    "heartbeatAt": _utc_now(),
                    "leaseExpiresAt": _lease_deadline(),
                    "startedAt": claimed.get("startedAt") or _utc_now(),
                    "updatedAt": _utc_now(),
                }
            )
            _write_labor_worker_job(claimed)
            return claimed
    return None


def heartbeat_labor_worker_job(
    job_id: str,
    *,
    owner_user_id: str,
    device_id: str,
    progress: dict[str, Any] | None = None,
    expected_task_generation_id: str = "",
) -> dict[str, Any]:
    store = _postgres_store()
    if store:
        try:
            return store.heartbeat(
                job_id,
                owner_user_id,
                device_id,
                progress,
                expected_task_generation_id,
            )
        except PermissionError as exc:
            raise LaborWorkerLeaseError(str(exc)) from exc
    with _STORE_LOCK:
        job = _assert_lease(
            job_id,
            owner_user_id,
            device_id,
            expected_task_generation_id=expected_task_generation_id,
        )
        job["heartbeatAt"] = _utc_now()
        job["leaseExpiresAt"] = _lease_deadline()
        job["updatedAt"] = _utc_now()
        if isinstance(progress, dict):
            job["progress"] = progress
        _write_labor_worker_job(job)
        return job


def complete_labor_worker_job(
    job_id: str,
    *,
    owner_user_id: str,
    device_id: str,
    expected_task_generation_id: str = "",
    expected_result_report_sha256: str = "",
    expected_result_report_size_bytes: int = 0,
    expected_result_input_fingerprint: str = "",
) -> dict[str, Any]:
    store = _postgres_store()
    if store:
        try:
            return store.complete(
                job_id,
                owner_user_id,
                device_id,
                expected_task_generation_id,
                expected_result_report_sha256,
                expected_result_report_size_bytes,
                expected_result_input_fingerprint,
            )
        except PermissionError as exc:
            raise LaborWorkerLeaseError(str(exc)) from exc
    with _STORE_LOCK:
        existing = get_labor_worker_job(job_id)
        if existing.get("status") == "succeeded":
            if existing.get("ownerUserId") != owner_user_id or existing.get("claimedDeviceId") != device_id:
                raise LaborWorkerLeaseError("任务不属于当前 Worker。")
            _assert_job_generation(existing, expected_task_generation_id)
            _assert_result_accepted(
                existing,
                expected_result_report_sha256,
                expected_result_report_size_bytes,
                expected_result_input_fingerprint,
            )
            return existing
        job = _assert_lease(
            job_id,
            owner_user_id,
            device_id,
            expected_task_generation_id=expected_task_generation_id,
        )
        _assert_result_accepted(
            job,
            expected_result_report_sha256,
            expected_result_report_size_bytes,
            expected_result_input_fingerprint,
        )
        job.update({"status": "succeeded", "finishedAt": _utc_now(), "updatedAt": _utc_now(), "leaseExpiresAt": ""})
        _write_labor_worker_job(job)
        return job


def fail_labor_worker_job(
    job_id: str,
    *,
    owner_user_id: str,
    device_id: str,
    error_code: str,
    error_message: str,
    retryable: bool,
    retry_delay_seconds: int = 30,
    expected_task_generation_id: str = "",
) -> dict[str, Any]:
    store = _postgres_store()
    if store:
        try:
            return store.fail(
                job_id,
                owner_user_id,
                device_id,
                error_code,
                error_message,
                retryable,
                retry_delay_seconds,
                expected_task_generation_id,
            )
        except PermissionError as exc:
            raise LaborWorkerLeaseError(str(exc)) from exc
    with _STORE_LOCK:
        job = _assert_lease(
            job_id,
            owner_user_id,
            device_id,
            expected_task_generation_id=expected_task_generation_id,
        )
        can_retry = bool(retryable) and int(job.get("attempt") or 0) < int(job.get("maxAttempts") or 1)
        job.update(
            {
                "status": "retry_wait" if can_retry else "failed",
                "availableAt": _utc_after(max(0, retry_delay_seconds)) if can_retry else job.get("availableAt", ""),
                "errorCode": str(error_code)[:80],
                "errorMessage": str(error_message)[:500],
                "leaseExpiresAt": "",
                "updatedAt": _utc_now(),
                "finishedAt": "" if can_retry else _utc_now(),
                **_empty_result_acceptance(),
            }
        )
        _write_labor_worker_job(job)
        return job


def mark_labor_worker_result_accepted(
    job_id: str,
    *,
    owner_user_id: str,
    device_id: str,
    expected_task_generation_id: str = "",
    result_report_sha256: str = "",
    result_report_size_bytes: int = 0,
    result_input_fingerprint: str = "",
) -> dict[str, Any]:
    report_sha256 = _required_sha256(result_report_sha256, "result_report_sha256")
    try:
        report_size = int(result_report_size_bytes)
    except (TypeError, ValueError) as exc:
        raise LaborWorkerLeaseError("result_report_size_bytes 必须是正整数。") from exc
    if isinstance(result_report_size_bytes, bool) or report_size <= 0:
        raise LaborWorkerLeaseError("result_report_size_bytes 必须是正整数。")
    input_fingerprint = _required_sha256(result_input_fingerprint, "result_input_fingerprint")
    store = _postgres_store()
    if store:
        try:
            return store.mark_result_accepted(
                job_id,
                owner_user_id,
                device_id,
                expected_task_generation_id,
                report_sha256,
                report_size,
                input_fingerprint,
            )
        except PermissionError as exc:
            raise LaborWorkerLeaseError(str(exc)) from exc
    with _STORE_LOCK:
        job = _assert_lease(
            job_id,
            owner_user_id,
            device_id,
            expected_task_generation_id=expected_task_generation_id,
        )
        job["resultAcceptedAt"] = _utc_now()
        job["resultAcceptedGenerationId"] = str(expected_task_generation_id or "").strip()
        job["resultAcceptedReportSha256"] = report_sha256
        job["resultAcceptedReportSizeBytes"] = report_size
        job["resultAcceptedInputFingerprint"] = input_fingerprint
        job["updatedAt"] = _utc_now()
        _write_labor_worker_job(job)
        return job


def clear_labor_worker_result_acceptance(
    job_id: str,
    *,
    owner_user_id: str,
    device_id: str,
    expected_task_generation_id: str = "",
) -> dict[str, Any]:
    store = _postgres_store()
    if store:
        try:
            return store.clear_result_acceptance(
                job_id,
                owner_user_id,
                device_id,
                expected_task_generation_id,
            )
        except PermissionError as exc:
            raise LaborWorkerLeaseError(str(exc)) from exc
    with _STORE_LOCK:
        job = _assert_lease(
            job_id,
            owner_user_id,
            device_id,
            expected_task_generation_id=expected_task_generation_id,
        )
        job.update(_empty_result_acceptance())
        job["updatedAt"] = _utc_now()
        _write_labor_worker_job(job)
        return job


def get_labor_worker_job(job_id: str) -> dict[str, Any]:
    store = _postgres_store()
    if store:
        return store.get(job_id)
    path = _job_path(job_id)
    if not path.exists():
        raise FileNotFoundError("海外劳务 Worker 任务不存在。")
    return json.loads(path.read_text(encoding="utf-8"))


def get_latest_labor_worker_job(
    run_id: str,
    *,
    task_generation_id: str | None = None,
    job_type: str = "",
    statuses: set[str] | None = None,
) -> dict[str, Any] | None:
    store = _postgres_store()
    if store:
        return store.find_latest(
            run_id,
            task_generation_id=task_generation_id,
            job_type=job_type,
            statuses=statuses,
        )
    normalized_statuses = {str(status) for status in (statuses or set()) if str(status)}
    matching = []
    for job in list_labor_worker_jobs():
        if str(job.get("runId") or "") != str(run_id):
            continue
        if task_generation_id is not None and str(job.get("taskGenerationId") or "") != str(task_generation_id):
            continue
        if job_type and str(job.get("jobType") or "reconcile") != str(job_type):
            continue
        if normalized_statuses and str(job.get("status") or "") not in normalized_statuses:
            continue
        matching.append(job)
    return max(
        matching,
        key=lambda row: (
            str(row.get("updatedAt") or row.get("createdAt") or ""),
            str(row.get("createdAt") or ""),
            str(row.get("id") or ""),
        ),
        default=None,
    )


def list_labor_worker_jobs() -> list[dict[str, Any]]:
    store = _postgres_store()
    if store:
        return store.list()
    if not LABOR_WORKER_JOBS_DIR.exists():
        return []
    rows = []
    for path in LABOR_WORKER_JOBS_DIR.glob("*/job.json"):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(rows, key=lambda row: (row.get("createdAt") or "", row.get("id") or ""))


def _assert_lease(
    job_id: str,
    owner_user_id: str,
    device_id: str,
    *,
    expected_task_generation_id: str = "",
) -> dict[str, Any]:
    job = get_labor_worker_job(job_id)
    if (
        job.get("status") != "running"
        or job.get("ownerUserId") != _required_identity(owner_user_id, "owner_user_id")
        or job.get("claimedDeviceId") != _required_identity(device_id, "device_id")
    ):
        raise LaborWorkerLeaseError("任务不属于当前 Worker，或租约已经失效。")
    if _parse_time(job.get("leaseExpiresAt"), default=datetime.min) <= datetime.utcnow():
        raise LaborWorkerLeaseError("任务租约已经过期。")
    _assert_job_generation(job, expected_task_generation_id)
    return dict(job)


def _assert_job_generation(job: dict[str, Any], expected_task_generation_id: str) -> None:
    expected = str(expected_task_generation_id or "").strip()
    actual = str(job.get("taskGenerationId") or "").strip()
    if actual != expected:
        raise LaborWorkerLeaseError("Worker 任务代次已失效，不能修改当前批次。")


def _assert_result_accepted(
    job: dict[str, Any],
    expected_report_sha256: str,
    expected_report_size_bytes: int,
    expected_input_fingerprint: str,
) -> None:
    generation = str(job.get("taskGenerationId") or "").strip()
    accepted_generation = str(job.get("resultAcceptedGenerationId") or "").strip()
    report_sha256 = str(expected_report_sha256 or "").strip().lower()
    try:
        report_size = int(expected_report_size_bytes)
    except (TypeError, ValueError):
        report_size = 0
    input_fingerprint = str(expected_input_fingerprint or "").strip().lower()
    if (
        not str(job.get("resultAcceptedAt") or "").strip()
        or accepted_generation != generation
        or not _is_sha256(report_sha256)
        or report_size <= 0
        or not _is_sha256(input_fingerprint)
        or str(job.get("resultAcceptedReportSha256") or "").strip().lower() != report_sha256
        or int(job.get("resultAcceptedReportSizeBytes") or 0) != report_size
        or str(job.get("resultAcceptedInputFingerprint") or "").strip().lower() != input_fingerprint
    ):
        raise LaborWorkerLeaseError("Worker 正式结果尚未通过服务端完整性校验，不能完成任务。")


def _supersede_local_job(job: dict[str, Any]) -> None:
    job.update(
        {
            "status": "failed",
            "errorCode": "TASK_GENERATION_SUPERSEDED",
            "errorMessage": "任务已被同一批次的新代次安全替代。",
            "leaseExpiresAt": "",
            "finishedAt": _utc_now(),
            "updatedAt": _utc_now(),
            **_empty_result_acceptance(),
        }
    )
    _write_labor_worker_job(job)


def _empty_result_acceptance() -> dict[str, Any]:
    return {
        "resultAcceptedAt": "",
        "resultAcceptedGenerationId": "",
        "resultAcceptedReportSha256": "",
        "resultAcceptedReportSizeBytes": 0,
        "resultAcceptedInputFingerprint": "",
    }


def _is_sha256(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return len(normalized) == 64 and all(character in "0123456789abcdef" for character in normalized)


def _required_sha256(value: str, field: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _is_sha256(normalized):
        raise LaborWorkerLeaseError(f"{field} 必须是 SHA-256。")
    return normalized


def _write_labor_worker_job(job: dict[str, Any]) -> None:
    path = _job_path(str(job.get("id") or ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _job_path(job_id: str) -> Path:
    if not str(job_id).startswith("labor_job_"):
        raise FileNotFoundError("海外劳务 Worker 任务不存在。")
    return LABOR_WORKER_JOBS_DIR / str(job_id) / "job.json"


def _required_identity(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise LaborWorkerLeaseError(f"缺少 {field}。")
    return normalized


def _required_job_type(value: str) -> str:
    normalized = str(value or "reconcile").strip().lower()
    if normalized not in SUPPORTED_JOB_TYPES:
        raise LaborWorkerLeaseError("未知的海外劳务 Worker 任务类型。")
    return normalized


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _utc_after(seconds: int) -> str:
    return (datetime.utcnow() + timedelta(seconds=seconds)).isoformat(timespec="seconds") + "Z"


def _lease_deadline() -> str:
    seconds = max(30, int(os.environ.get("SIGMA_LABOR_WORKER_LEASE_SECONDS", DEFAULT_LEASE_SECONDS)))
    return _utc_after(seconds)


def _parse_time(value: Any, *, default: datetime) -> datetime:
    try:
        return datetime.fromisoformat(str(value or "").removesuffix("Z"))
    except (TypeError, ValueError):
        return default


def labor_worker_job_store_health() -> dict[str, Any]:
    store = _postgres_store()
    if store:
        return store.health()
    serverless = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))
    return {
        "backend": "local-json",
        "configured": True,
        "ready": not serverless,
        "error": "Vercel 运行个人 Worker 必须配置 Postgres 队列。" if serverless else "",
    }


def _postgres_store() -> PostgresLaborWorkerStore | None:
    backend = os.environ.get("SIGMA_LABOR_JOB_BACKEND", "").strip().lower()
    if backend not in {"postgres", "postgresql", "supabase"}:
        return None
    database_url = str(
        os.environ.get("SIGMA_LABOR_JOB_DATABASE_URL")
        or os.environ.get("SIGMA_LABOR_DATABASE_URL")
        or os.environ.get("ADMIN_DATABASE_URL")
        or os.environ.get("LABOR_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()
    if not database_url:
        raise RuntimeError("已启用 Postgres Worker 队列，但未配置数据库连接。")
    lease_seconds = int(os.environ.get("SIGMA_LABOR_WORKER_LEASE_SECONDS", DEFAULT_LEASE_SECONDS))
    return PostgresLaborWorkerStore(database_url, lease_seconds=lease_seconds)
