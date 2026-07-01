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
JOB_LEASE_SECONDS = 120
_POSTGRES_SCHEMA_READY = False
_MYSQL_SCHEMA_READY = False
_SQL_STORE_BACKEND = ""
SERVERLESS_QUEUE_ERROR = "海外劳务 Worker 队列需要配置 Postgres/MySQL 数据库连接。"


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
        is_available = job.get("status") in {"queued", "retry_wait"} and (
            not _parse_time(job.get("availableAt")) or _parse_time(job.get("availableAt")) <= now_dt
        )
        is_expired_running = job.get("status") == "running" and (
            not _parse_time(job.get("leaseExpiresAt")) or _parse_time(job.get("leaseExpiresAt")) <= now_dt
        )
        if not is_available and not is_expired_running:
            continue
        claimed = dict(job)
        claimed["status"] = "running"
        claimed["workerId"] = worker_id
        claimed["attempt"] = int(claimed.get("attempt") or 0) + 1
        claimed["startedAt"] = claimed.get("startedAt") or _now()
        claimed["heartbeatAt"] = _now()
        claimed["leaseExpiresAt"] = _lease_expires_at()
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


def heartbeat_labor_job(job_id: str, worker_id: str) -> dict[str, Any]:
    if _use_postgres_jobs():
        return _heartbeat_postgres_job(job_id, worker_id)
    job = _load_job(job_id)
    if job.get("status") != "running" or job.get("workerId") != worker_id:
        return job
    job["heartbeatAt"] = _now()
    job["leaseExpiresAt"] = _lease_expires_at()
    job["updatedAt"] = _now()
    _write_job(job)
    return job


def get_labor_job(job_id: str) -> dict[str, Any]:
    return _load_job(job_id)


def ensure_labor_worker_job_store_ready() -> None:
    if _serverless_requires_durable_job_store():
        raise RuntimeError(SERVERLESS_QUEUE_ERROR)


def labor_worker_job_store_health(*, probe: bool = False) -> dict[str, Any]:
    enabled = labor_worker_jobs_enabled()
    database_url_configured = bool(_job_database_url())
    backend = _job_backend() or ("postgres" if _use_postgres_jobs() else "local-json")
    serverless = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV") or os.environ.get("VERCEL_URL"))
    health: dict[str, Any] = {
        "enabled": enabled,
        "backend": backend,
        "serverless": serverless,
        "databaseUrlConfigured": database_url_configured,
        "probe": bool(probe),
        "ok": True,
    }
    if enabled and serverless and not database_url_configured:
        health.update(
            {
                "ok": False,
                "errorCode": "LABOR_WORKER_QUEUE_UNAVAILABLE",
                "message": SERVERLESS_QUEUE_ERROR,
            }
        )
        return health
    if probe and backend in ("postgres", "mysql"):
        try:
            _ensure_postgres_schema()
        except Exception as exc:
            health.update(
                {
                    "ok": False,
                    "errorCode": "LABOR_WORKER_QUEUE_PROBE_FAILED",
                    "errorType": type(exc).__name__,
                    "message": str(exc)[:240],
                }
            )
    return health


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


def _lease_expires_at() -> str:
    return (datetime.utcnow() + timedelta(seconds=JOB_LEASE_SECONDS)).isoformat(timespec="seconds")


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


def _job_backend() -> str:
    """Return the specific durable DB backend: 'postgres' or 'mysql'."""
    backend = os.environ.get("SIGMA_LABOR_JOB_BACKEND", "").strip().lower()
    if backend in {"postgres", "postgresql", "supabase"}:
        return "postgres"
    if backend in {"mysql"}:
        return "mysql"
    database_url = _job_database_url()
    if database_url.startswith("mysql://"):
        return "mysql"
    if database_url.startswith(("postgres://", "postgresql://")) or database_url:
        return "postgres"
    return ""


def _use_postgres_jobs() -> bool:
    backend = os.environ.get("SIGMA_LABOR_JOB_BACKEND", "").strip().lower()
    if backend in {"local", "json", "file", "files"}:
        return False
    if backend in {"postgres", "postgresql", "supabase", "mysql"}:
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


class _MySQLJobConnection:
    """将 PyMySQL connection 包装为 psycopg/sqlite3 风格的 conn.execute() 接口。"""

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._cursor: Any = None

    def __enter__(self) -> "_MySQLJobConnection":
        self._cursor = self._conn.cursor()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._cursor:
            self._cursor.close()
        self._conn.close()

    def execute(self, sql: str, params: Any = ()) -> Any:
        self._cursor.execute(sql, params)
        return self._cursor

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()


def _connect_mysql():
    try:
        import pymysql
        from urllib.parse import unquote
    except Exception as exc:  # pragma: no cover - dependency is declared in requirements
        raise RuntimeError("MySQL labor job store requires PyMySQL") from exc
    from urllib.parse import urlparse
    parsed = urlparse(_job_database_url())
    conn = pymysql.connect(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 3306,
        user=parsed.username or "root",
        password=unquote(parsed.password) if parsed.password else "",
        database=(parsed.path or "/sigma").lstrip("/") or "sigma",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=5,
        read_timeout=30,
    )
    return _MySQLJobConnection(conn)


def _connect_durable_db():
    if _job_backend() == "mysql":
        return _connect_mysql()
    return _connect_postgres()


def _ensure_postgres_schema() -> None:
    global _POSTGRES_SCHEMA_READY, _MYSQL_SCHEMA_READY, _SQL_STORE_BACKEND
    backend = _job_backend()
    if backend == "postgres" and _POSTGRES_SCHEMA_READY:
        return
    if backend == "mysql" and _MYSQL_SCHEMA_READY:
        return
    if backend == "mysql":
        statements = _mysql_schema_statements()
    else:
        statements = _postgres_schema_statements()
    conn = _connect_durable_db()
    with conn:
        for statement in statements:
            conn.execute(statement)
        if backend == "mysql":
            _ensure_mysql_indexes(conn)
        conn.commit()
    if backend == "mysql":
        _MYSQL_SCHEMA_READY = True
        _SQL_STORE_BACKEND = "mysql"
    else:
        _POSTGRES_SCHEMA_READY = True
        _SQL_STORE_BACKEND = "postgres"


def _postgres_schema_statements() -> list[str]:
    return [
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
        """
        create index if not exists labor_jobs_running_lease_idx
        on labor_jobs(status, lease_expires_at)
        where status = 'running'
        """,
    ]


def _mysql_schema_statements() -> list[str]:
    return [
        """
        create table if not exists labor_jobs (
            id varchar(255) primary key,
            run_id varchar(255) not null,
            job_type varchar(50) not null default 'reconcile',
            status varchar(50) not null default 'queued',
            priority integer not null default 100,
            attempt integer not null default 0,
            max_attempts integer not null default 5,
            available_at timestamp not null default current_timestamp,
            worker_id varchar(255),
            lease_expires_at timestamp null,
            heartbeat_at timestamp null,
            error_code varchar(100),
            error_detail text,
            retryable tinyint(1) not null default 0,
            metadata_snapshot json not null,
            created_at timestamp not null default current_timestamp,
            started_at timestamp null,
            finished_at timestamp null,
            updated_at timestamp not null default current_timestamp
        ) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci
        """,
        # MySQL 不支持 CREATE INDEX IF NOT EXISTS，改为靠 Python 层处理错误
    ]


def _ensure_mysql_indexes(conn: Any) -> None:
    """MySQL 不支持 CREATE INDEX IF NOT EXISTS，尝试创建并忽略重复错误。"""
    indexes = [
        "create index labor_jobs_claim_idx on labor_jobs(status, available_at, priority, created_at)",
        "create index labor_jobs_running_lease_idx on labor_jobs(status, lease_expires_at)",
    ]
    for sql in indexes:
        try:
            conn.execute(sql)
        except Exception:
            pass  # index already exists


def _claim_next_postgres_job(worker_id: str) -> dict[str, Any] | None:
    _ensure_postgres_schema()
    backend = _job_backend()
    if backend == "mysql":
        return _claim_next_mysql_job(worker_id)
    with _connect_postgres() as conn:
        row = conn.execute(
            """
            with next_job as (
                select id
                from labor_jobs
                where (
                    status in ('queued', 'retry_wait')
                    and available_at <= now()
                )
                or (
                    status = 'running'
                    and (lease_expires_at is null or lease_expires_at <= now())
                )
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
                lease_expires_at = now() + (%s * interval '1 second'),
                updated_at = now()
            from next_job
            where job.id = next_job.id
            returning job.*
            """,
            (worker_id, JOB_LEASE_SECONDS),
        ).fetchone()
        conn.commit()
    if not row:
        return None
    return _row_to_job(dict(row))


def _claim_next_mysql_job(worker_id: str) -> dict[str, Any] | None:
    """MySQL-compatible job claim: SELECT FOR UPDATE → UPDATE → SELECT (no RETURNING)."""
    with _connect_mysql() as conn:
        # Step 1: find a claimable job
        row = conn.execute(
            """
            select id
            from labor_jobs
            where (
                status in ('queued', 'retry_wait')
                and available_at <= now()
            )
            or (
                status = 'running'
                and (lease_expires_at is null or lease_expires_at <= now())
            )
            order by priority desc, created_at
            limit 1
            for update skip locked
            """,
        ).fetchone()
        if not row:
            conn.commit()
            return None
        job_id = row["id"]
        # Step 2: update it
        conn.execute(
            """
            update labor_jobs
            set status = 'running',
                worker_id = %s,
                attempt = attempt + 1,
                started_at = coalesce(started_at, now()),
                heartbeat_at = now(),
                lease_expires_at = now() + interval 1 second * %s,
                updated_at = now()
            where id = %s
            """,
            (worker_id, JOB_LEASE_SECONDS, job_id),
        )
        # Step 3: read back the updated row
        updated = conn.execute("select * from labor_jobs where id = %s", (job_id,)).fetchone()
        conn.commit()
    if not updated:
        return None
    return _row_to_job(dict(updated))


def _heartbeat_postgres_job(job_id: str, worker_id: str) -> dict[str, Any]:
    _ensure_postgres_schema()
    backend = _job_backend()
    if backend == "mysql":
        with _connect_mysql() as conn:
            conn.execute(
                """
                update labor_jobs
                set heartbeat_at = now(),
                    lease_expires_at = now() + interval 1 second * %s,
                    updated_at = now()
                where id = %s
                  and status = 'running'
                  and worker_id = %s
                """,
                (JOB_LEASE_SECONDS, job_id, worker_id),
            )
            conn.commit()
            row = conn.execute("select * from labor_jobs where id = %s", (job_id,)).fetchone()
        if row:
            return _row_to_job(dict(row))
        return _load_postgres_job(job_id)
    with _connect_postgres() as conn:
        row = conn.execute(
            """
            update labor_jobs
            set heartbeat_at = now(),
                lease_expires_at = now() + (%s * interval '1 second'),
                updated_at = now()
            where id = %s
              and status = 'running'
              and worker_id = %s
            returning *
            """,
            (JOB_LEASE_SECONDS, job_id, worker_id),
        ).fetchone()
        conn.commit()
    if row:
        return _row_to_job(dict(row))
    return _load_postgres_job(job_id)


def _list_postgres_jobs() -> list[dict[str, Any]]:
    _ensure_postgres_schema()
    conn = _connect_durable_db()
    with conn:
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
    conn = _connect_durable_db()
    with conn:
        row = conn.execute("select * from labor_jobs where id = %s", (job_id,)).fetchone()
    if not row:
        raise FileNotFoundError("劳务核对任务不存在。")
    return _row_to_job(dict(row))


def _write_postgres_job(job: dict[str, Any]) -> None:
    _ensure_postgres_schema()
    row = _job_to_row(job)
    backend = _job_backend()
    if backend == "mysql":
        with _connect_mysql() as conn:
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
                on duplicate key update
                    status = values(status),
                    priority = values(priority),
                    attempt = values(attempt),
                    max_attempts = values(max_attempts),
                    available_at = values(available_at),
                    worker_id = values(worker_id),
                    lease_expires_at = values(lease_expires_at),
                    heartbeat_at = values(heartbeat_at),
                    error_code = values(error_code),
                    error_detail = values(error_detail),
                    retryable = values(retryable),
                    metadata_snapshot = values(metadata_snapshot),
                    started_at = values(started_at),
                    finished_at = values(finished_at),
                    updated_at = values(updated_at)
                """,
                row,
            )
            conn.commit()
        return
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
    if _job_backend() == "mysql":
        # PyMySQL accepts dicts directly — it serialises to JSON internally
        return json.dumps(value, ensure_ascii=False)
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
