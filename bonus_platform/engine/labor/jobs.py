from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from ...config import OUTPUT_DIR


LABOR_JOBS_DIR = OUTPUT_DIR / "labor_jobs"
JOB_FILE = "job.json"
ACTIVE_JOB_STATUSES = {"queued", "running", "retry_wait"}
_POSTGRES_SCHEMA_READY = False
SERVERLESS_QUEUE_ERROR = "海外劳务 Worker 队列需要配置 Postgres 数据库连接。"


def labor_worker_jobs_enabled() -> bool:
    mode = os.environ.get("SIGMA_LABOR_EXECUTION_MODE", "").strip().lower()
    if mode in {"worker", "workers", "job", "jobs", "queue", "queued"}:
        return True
    if mode in {"inline", "legacy", "local", "thread", "threads", "off", "false", "0"}:
        return False
    access = os.environ.get("SIGMA_OVERSEAS_LABOR_ACCESS", "").strip().lower()
    return bool(os.environ.get("VERCEL")) and access in {"production", "prod", "enabled", "full", "online"}


def enqueue_labor_reconciliation_job(run_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    ensure_labor_worker_job_store_ready()
    existing = _active_job_for_run(run_id)
    if existing:
        return existing
    now = _now()
    job = {
        "id": _new_job_id(),
        "runId": run_id,
        "jobType": "reconcile",
        "status": "queued",
        "priority": 100,
        "attempt": 0,
        "maxAttempts": 5,
        "availableAt": now,
        "workerId": "",
        "leaseExpiresAt": "",
        "heartbeatAt": "",
        "errorCode": "",
        "errorDetail": "",
        "retryable": False,
        "createdAt": now,
        "updatedAt": now,
        "startedAt": "",
        "finishedAt": "",
        "metadataSnapshot": _job_metadata_snapshot(metadata or {}),
    }
    _write_job(job)
    return job


def claim_next_labor_job(worker_id: str) -> dict[str, Any] | None:
    if _use_postgres_jobs():
        return _claim_next_postgres_job(worker_id)
    now_dt = datetime.utcnow()
    for job in _list_jobs():
        if job.get("status") not in {"queued", "retry_wait"}:
            continue
        if _parse_time(job.get("availableAt")) and _parse_time(job.get("availableAt")) > now_dt:
            continue
        claimed = dict(job)
        claimed["status"] = "running"
        claimed["workerId"] = worker_id
        claimed["attempt"] = int(claimed.get("attempt") or 0) + 1
        claimed["startedAt"] = claimed.get("startedAt") or _now()
        claimed["heartbeatAt"] = _now()
        claimed["leaseExpiresAt"] = (datetime.utcnow() + timedelta(minutes=2)).isoformat(timespec="seconds")
        claimed["updatedAt"] = _now()
        _write_job(claimed)
        return claimed
    return None


def complete_labor_job(job_id: str, updates: dict[str, Any] | None = None) -> dict[str, Any]:
    job = _load_job(job_id)
    job.update(updates or {})
    job["status"] = "succeeded"
    job["retryable"] = False
    job["errorCode"] = ""
    job["errorDetail"] = ""
    job["finishedAt"] = _now()
    job["updatedAt"] = _now()
    _write_job(job)
    return job


def fail_labor_job(job_id: str, message: str, *, retryable: bool = False, error_code: str = "LABOR_JOB_FAILED") -> dict[str, Any]:
    job = _load_job(job_id)
    job["status"] = "retry_wait" if retryable and int(job.get("attempt") or 0) < int(job.get("maxAttempts") or 5) else "failed"
    job["errorCode"] = error_code
    job["errorDetail"] = str(message)
    job["retryable"] = bool(retryable and job["status"] == "retry_wait")
    job["availableAt"] = _next_retry_at(job) if job["status"] == "retry_wait" else job.get("availableAt", "")
    job["finishedAt"] = _now() if job["status"] == "failed" else ""
    job["updatedAt"] = _now()
    _write_job(job)
    return job


def get_labor_job(job_id: str) -> dict[str, Any]:
    return _load_job(job_id)


def ensure_labor_worker_job_store_ready() -> None:
    if _serverless_requires_durable_job_store():
        raise RuntimeError(SERVERLESS_QUEUE_ERROR)


def _active_job_for_run(run_id: str) -> dict[str, Any] | None:
    for job in _list_jobs():
        if job.get("runId") == run_id and job.get("jobType") == "reconcile" and job.get("status") in ACTIVE_JOB_STATUSES:
            return job
    return None


def _list_jobs() -> list[dict[str, Any]]:
    if _use_postgres_jobs():
        return _list_postgres_jobs()
    if not LABOR_JOBS_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in LABOR_JOBS_DIR.glob(f"*/{JOB_FILE}"):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(rows, key=lambda row: (int(row.get("priority") or 100), row.get("createdAt") or ""))


def _load_job(job_id: str) -> dict[str, Any]:
    if _use_postgres_jobs():
        return _load_postgres_job(job_id)
    path = _job_path(job_id)
    if not path.exists():
        raise FileNotFoundError("劳务核对任务不存在。")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_job(job: dict[str, Any]) -> None:
    if _use_postgres_jobs():
        _write_postgres_job(job)
        return
    path = _job_path(str(job["id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def _job_path(job_id: str) -> Path:
    if not job_id.startswith("labor_job_"):
        raise FileNotFoundError("劳务核对任务不存在。")
    return LABOR_JOBS_DIR / job_id / JOB_FILE


def _new_job_id() -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    return f"labor_job_{timestamp}_{uuid4().hex[:8]}"


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _next_retry_at(job: dict[str, Any]) -> str:
    attempt = max(int(job.get("attempt") or 1), 1)
    delay_seconds = [30, 120, 600, 1800][min(attempt - 1, 3)]
    return (datetime.utcnow() + timedelta(seconds=delay_seconds)).isoformat(timespec="seconds")


def _job_metadata_snapshot(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "supplierName": metadata.get("supplierName") or metadata.get("supplier_name") or "",
        "periodStart": metadata.get("periodStart") or metadata.get("period_start") or "",
        "periodEnd": metadata.get("periodEnd") or metadata.get("period_end") or "",
        "currency": metadata.get("currency") or "",
        "inputManifestHash": metadata.get("inputManifestHash") or metadata.get("input_manifest_hash") or "",
    }


def _use_postgres_jobs() -> bool:
    backend = os.environ.get("SIGMA_LABOR_JOB_BACKEND", "").strip().lower()
    if backend in {"local", "json", "file", "files"}:
        return False
    if backend in {"postgres", "postgresql", "supabase"}:
        return bool(_job_database_url())
    return labor_worker_jobs_enabled() and bool(_job_database_url())


def _serverless_requires_durable_job_store() -> bool:
    return bool(os.environ.get("VERCEL")) and labor_worker_jobs_enabled() and not _job_database_url()


def _job_database_url() -> str:
    return (
        os.environ.get("SIGMA_LABOR_JOB_DATABASE_URL")
        or os.environ.get("LABOR_DATABASE_URL")
        or os.environ.get("ADMIN_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()


def _connect_postgres():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:  # pragma: no cover - dependency is declared in requirements
        raise RuntimeError("Postgres labor job store requires psycopg[binary]") from exc
    return psycopg.connect(_job_database_url(), row_factory=dict_row)


def _ensure_postgres_schema() -> None:
    global _POSTGRES_SCHEMA_READY
    if _POSTGRES_SCHEMA_READY:
        return
    statements = [
        """
        create table if not exists labor_jobs (
            id text primary key,
            run_id text not null,
            job_type text not null default 'reconcile',
            status text not null default 'queued',
            priority integer not null default 100,
            attempt integer not null default 0,
            max_attempts integer not null default 5,
            available_at timestamptz not null default now(),
            worker_id text,
            lease_expires_at timestamptz,
            heartbeat_at timestamptz,
            error_code text,
            error_detail text,
            retryable boolean not null default false,
            metadata_snapshot jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            started_at timestamptz,
            finished_at timestamptz,
            updated_at timestamptz not null default now()
        )
        """,
        """
        create unique index if not exists labor_one_active_job_per_run
        on labor_jobs(run_id)
        where status in ('queued', 'running', 'retry_wait')
        """,
        """
        create index if not exists labor_jobs_claim_idx
        on labor_jobs(status, available_at, priority desc, created_at)
        """,
    ]
    with _connect_postgres() as conn:
        for statement in statements:
            conn.execute(statement)
        conn.commit()
    _POSTGRES_SCHEMA_READY = True


def _claim_next_postgres_job(worker_id: str) -> dict[str, Any] | None:
    _ensure_postgres_schema()
    with _connect_postgres() as conn:
        row = conn.execute(
            """
            with next_job as (
                select id
                from labor_jobs
                where status in ('queued', 'retry_wait')
                  and available_at <= now()
                order by priority desc, created_at
                for update skip locked
                limit 1
            )
            update labor_jobs job
            set status = 'running',
                worker_id = %s,
                attempt = job.attempt + 1,
                started_at = coalesce(job.started_at, now()),
                heartbeat_at = now(),
                lease_expires_at = now() + interval '2 minutes',
                updated_at = now()
            from next_job
            where job.id = next_job.id
            returning job.*
            """,
            (worker_id,),
        ).fetchone()
        conn.commit()
    if not row:
        return None
    return _row_to_job(dict(row))


def _list_postgres_jobs() -> list[dict[str, Any]]:
    _ensure_postgres_schema()
    with _connect_postgres() as conn:
        rows = conn.execute(
            """
            select *
            from labor_jobs
            order by priority desc, created_at
            """
        ).fetchall()
    return [_row_to_job(dict(row)) for row in rows]


def _load_postgres_job(job_id: str) -> dict[str, Any]:
    _ensure_postgres_schema()
    with _connect_postgres() as conn:
        row = conn.execute("select * from labor_jobs where id = %s", (job_id,)).fetchone()
    if not row:
        raise FileNotFoundError("劳务核对任务不存在。")
    return _row_to_job(dict(row))


def _write_postgres_job(job: dict[str, Any]) -> None:
    _ensure_postgres_schema()
    row = _job_to_row(job)
    with _connect_postgres() as conn:
        conn.execute(
            """
            insert into labor_jobs (
                id, run_id, job_type, status, priority, attempt, max_attempts,
                available_at, worker_id, lease_expires_at, heartbeat_at,
                error_code, error_detail, retryable, metadata_snapshot,
                created_at, started_at, finished_at, updated_at
            )
            values (
                %(id)s, %(run_id)s, %(job_type)s, %(status)s, %(priority)s, %(attempt)s, %(max_attempts)s,
                %(available_at)s, %(worker_id)s, %(lease_expires_at)s, %(heartbeat_at)s,
                %(error_code)s, %(error_detail)s, %(retryable)s, %(metadata_snapshot)s,
                %(created_at)s, %(started_at)s, %(finished_at)s, %(updated_at)s
            )
            on conflict (id) do update set
                status = excluded.status,
                priority = excluded.priority,
                attempt = excluded.attempt,
                max_attempts = excluded.max_attempts,
                available_at = excluded.available_at,
                worker_id = excluded.worker_id,
                lease_expires_at = excluded.lease_expires_at,
                heartbeat_at = excluded.heartbeat_at,
                error_code = excluded.error_code,
                error_detail = excluded.error_detail,
                retryable = excluded.retryable,
                metadata_snapshot = excluded.metadata_snapshot,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                updated_at = excluded.updated_at
            """,
            row,
        )
        conn.commit()


def _job_to_row(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job.get("id"),
        "run_id": job.get("runId"),
        "job_type": job.get("jobType") or "reconcile",
        "status": job.get("status") or "queued",
        "priority": int(job.get("priority") or 100),
        "attempt": int(job.get("attempt") or 0),
        "max_attempts": int(job.get("maxAttempts") or 5),
        "available_at": _db_time(job.get("availableAt")) or _now(),
        "worker_id": job.get("workerId") or None,
        "lease_expires_at": _db_time(job.get("leaseExpiresAt")),
        "heartbeat_at": _db_time(job.get("heartbeatAt")),
        "error_code": job.get("errorCode") or None,
        "error_detail": job.get("errorDetail") or None,
        "retryable": bool(job.get("retryable")),
        "metadata_snapshot": _jsonb_param(job.get("metadataSnapshot") or {}),
        "created_at": _db_time(job.get("createdAt")) or _now(),
        "started_at": _db_time(job.get("startedAt")),
        "finished_at": _db_time(job.get("finishedAt")),
        "updated_at": _db_time(job.get("updatedAt")) or _now(),
    }


def _row_to_job(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id") or "",
        "runId": row.get("run_id") or "",
        "jobType": row.get("job_type") or "reconcile",
        "status": row.get("status") or "queued",
        "priority": int(row.get("priority") or 100),
        "attempt": int(row.get("attempt") or 0),
        "maxAttempts": int(row.get("max_attempts") or 5),
        "availableAt": _format_db_time(row.get("available_at")),
        "workerId": row.get("worker_id") or "",
        "leaseExpiresAt": _format_db_time(row.get("lease_expires_at")),
        "heartbeatAt": _format_db_time(row.get("heartbeat_at")),
        "errorCode": row.get("error_code") or "",
        "errorDetail": row.get("error_detail") or "",
        "retryable": bool(row.get("retryable")),
        "metadataSnapshot": _json_dict(row.get("metadata_snapshot")),
        "createdAt": _format_db_time(row.get("created_at")),
        "startedAt": _format_db_time(row.get("started_at")),
        "finishedAt": _format_db_time(row.get("finished_at")),
        "updatedAt": _format_db_time(row.get("updated_at")),
    }


def _db_time(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _format_db_time(value: Any) -> str:
    if not value:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat(timespec="seconds")
    return str(value)


def _jsonb_param(value: dict[str, Any]) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except Exception:  # pragma: no cover - exercised only when Postgres dependency is absent
        return json.dumps(value, ensure_ascii=False)
    return Jsonb(value)


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
