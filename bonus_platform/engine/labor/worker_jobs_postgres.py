from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable
from uuid import uuid4

from .worker_version import worker_version_at_least, worker_version_code


class PostgresLaborWorkerStore:
    def __init__(self, database_url: str, *, lease_seconds: int = 120, connect: Callable | None = None) -> None:
        self.database_url = str(database_url or "").strip()
        self.lease_seconds = max(30, int(lease_seconds))
        self._connect_override = connect

    def health(self) -> dict[str, Any]:
        try:
            with self._connect() as conn:
                row = conn.execute("select to_regclass('public.labor_jobs') as table_name").fetchone()
            ready = bool(row and row.get("table_name"))
            return {"backend": "postgres", "configured": True, "ready": ready}
        except Exception as exc:  # noqa: BLE001 - health endpoint must return diagnostics.
            return {
                "backend": "postgres",
                "configured": True,
                "ready": False,
                "errorType": type(exc).__name__[:96],
            }

    def enqueue(
        self,
        run_id: str,
        owner: str,
        required_version: str,
        max_attempts: int,
        task_generation_id: str = "",
        job_type: str = "reconcile",
    ) -> dict[str, Any]:
        generation = str(task_generation_id or "").strip()
        normalized_job_type = _job_type(job_type)
        with self._connect() as conn:
            existing = conn.execute(
                """select * from labor_jobs where run_id=%s
                   and status in ('queued','running','retry_wait') order by created_at limit 1
                   for update""",
                (run_id,),
            ).fetchone()
            if existing:
                job = self._row(dict(existing))
                if job["ownerUserId"] != owner:
                    raise PermissionError("批次任务归属与当前用户不一致。")
                if job["taskGenerationId"] == generation and job["jobType"] == normalized_job_type:
                    existing = self._upgrade_waiting_job_required_version(conn, dict(existing), required_version)
                    conn.commit()
                    return self._row(existing)
                if job["taskGenerationId"] and not generation:
                    raise PermissionError("当前批次已绑定新的任务代次，不能复用无代次 Worker 任务。")
                self._supersede_active_job(conn, job["id"])
            row = self._insert_job(
                conn,
                run_id,
                owner,
                required_version,
                max_attempts,
                generation,
                normalized_job_type,
            )
            try:
                conn.commit()
            except Exception:
                raise
        return self._row(dict(row))

    def _insert_job(
        self,
        conn: Any,
        run_id: str,
        owner: str,
        required_version: str,
        max_attempts: int,
        generation: str,
        job_type: str,
    ) -> Any:
        job_id = f"labor_job_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}_{uuid4().hex[:8]}"
        metadata = json.dumps(
            {
                "ownerUserId": owner,
                "requiredWorkerVersion": required_version,
                "requiredWorkerVersionCode": _version_code(required_version),
                "taskGenerationId": generation,
                "progress": {},
                "resultAcceptedAt": "",
                "resultAcceptedGenerationId": "",
                "resultAcceptedReportSha256": "",
                "resultAcceptedReportSizeBytes": 0,
                "resultAcceptedInputFingerprint": "",
            },
            ensure_ascii=False,
        )
        try:
            return conn.execute(
                """insert into labor_jobs (
                       id, run_id, job_type, status, priority, attempt, max_attempts,
                       available_at, retryable, metadata_snapshot, created_at, updated_at
                   ) values (%s,%s,%s,'queued',100,0,%s,now(),false,%s::jsonb,now(),now())
                   returning *""",
                (job_id, run_id, job_type, max(1, int(max_attempts)), metadata),
            ).fetchone()
        except Exception as exc:  # noqa: BLE001 - normalize concurrent unique-index race.
            if getattr(exc, "sqlstate", "") != "23505":
                raise
            conn.rollback()
            row = conn.execute(
                """select * from labor_jobs where run_id=%s
                   and status in ('queued','running','retry_wait') order by created_at limit 1
                   for update""",
                (run_id,),
            ).fetchone()
            if not row:
                raise
            concurrent = self._row(dict(row))
            if concurrent["ownerUserId"] != owner:
                raise PermissionError("批次任务归属与当前用户不一致。") from exc
            if concurrent["taskGenerationId"] == generation and concurrent["jobType"] == job_type:
                return self._upgrade_waiting_job_required_version(conn, dict(row), required_version)
            if concurrent["taskGenerationId"] and not generation:
                raise PermissionError("当前批次已绑定新的任务代次，不能复用无代次 Worker 任务。") from exc
            self._supersede_active_job(conn, concurrent["id"])
            return self._insert_job(conn, run_id, owner, required_version, max_attempts, generation, job_type)

    @staticmethod
    def _supersede_active_job(conn: Any, job_id: str) -> None:
        updated = conn.execute(
            """update labor_jobs set status='failed', retryable=false,
                   error_code=%s, error_detail=%s, lease_expires_at=null,
                   finished_at=now(), updated_at=now(),
                   metadata_snapshot=metadata_snapshot
                       - 'resultAcceptedAt' - 'resultAcceptedGenerationId'
                       - 'resultAcceptedReportSha256' - 'resultAcceptedReportSizeBytes'
                       - 'resultAcceptedInputFingerprint'
               where id=%s and status in ('queued','running','retry_wait')
               returning *""",
            (
                "TASK_GENERATION_SUPERSEDED",
                "任务已被同一批次的新代次安全替代。",
                job_id,
            ),
        ).fetchone()
        if not updated:
            raise PermissionError("旧 Worker 任务已变化，不能安全复用。")

    def _upgrade_waiting_job_required_version(
        self,
        conn: Any,
        row: dict[str, Any],
        required_version: str,
    ) -> dict[str, Any]:
        job = self._row(row)
        if (
            job["status"] not in {"queued", "retry_wait"}
            or not str(required_version or "").strip()
            or worker_version_at_least(job["requiredWorkerVersion"], required_version)
        ):
            return row
        updated = conn.execute(
            """update labor_jobs set
                   metadata_snapshot=jsonb_set(
                       jsonb_set(metadata_snapshot,'{requiredWorkerVersion}',to_jsonb(%s::text),true),
                       '{requiredWorkerVersionCode}',to_jsonb(%s::bigint),true
                   ), updated_at=now()
               where id=%s and status in ('queued','retry_wait')
               returning *""",
            (required_version, _version_code(required_version), job["id"]),
        ).fetchone()
        if not updated:
            raise RuntimeError("等待中的海外劳务 Worker 任务最低版本提升失败。")
        return dict(updated)

    def claim(self, owner: str, device: str, worker_version: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """with next_job as (
                       select id from labor_jobs
                       where metadata_snapshot->>'ownerUserId'=%s
                         and coalesce((metadata_snapshot->>'requiredWorkerVersionCode')::bigint,0) <= %s
                         and attempt < max_attempts
                         and ((status in ('queued','retry_wait') and available_at <= now())
                           or (status='running' and (lease_expires_at is null or lease_expires_at <= now())))
                       order by priority desc, created_at
                       for update skip locked limit 1
                   )
                   update labor_jobs job set status='running', worker_id=%s,
                       attempt=job.attempt+1, started_at=coalesce(job.started_at,now()),
                       heartbeat_at=now(), lease_expires_at=now()+(%s*interval '1 second'), updated_at=now()
                   from next_job where job.id=next_job.id returning job.*""",
                (owner, _version_code(worker_version), device, self.lease_seconds),
            ).fetchone()
            conn.commit()
        return self._row(dict(row)) if row else None

    def heartbeat(
        self,
        job_id: str,
        owner: str,
        device: str,
        progress: dict[str, Any] | None,
        expected_task_generation_id: str = "",
    ) -> dict[str, Any]:
        progress_json = json.dumps(progress or {}, ensure_ascii=False)
        with self._connect() as conn:
            row = conn.execute(
                """update labor_jobs set heartbeat_at=now(),
                       lease_expires_at=now()+(%s*interval '1 second'),
                       metadata_snapshot=jsonb_set(metadata_snapshot,'{progress}',%s::jsonb,true), updated_at=now()
                   where id=%s and status='running' and worker_id=%s
                     and metadata_snapshot->>'ownerUserId'=%s
                     and coalesce(metadata_snapshot->>'taskGenerationId','')=%s
                     and lease_expires_at > now()
                   returning *""",
                (
                    self.lease_seconds,
                    progress_json,
                    job_id,
                    device,
                    owner,
                    str(expected_task_generation_id or "").strip(),
                ),
            ).fetchone()
            conn.commit()
        return self._leased_row(row)

    def complete(
        self,
        job_id: str,
        owner: str,
        device: str,
        expected_task_generation_id: str = "",
        expected_result_report_sha256: str = "",
        expected_result_report_size_bytes: int = 0,
        expected_result_input_fingerprint: str = "",
    ) -> dict[str, Any]:
        existing = self.get(job_id)
        if existing["status"] == "succeeded":
            if existing["ownerUserId"] != owner or existing["claimedDeviceId"] != device:
                raise PermissionError("任务不属于当前 Worker。")
            self._assert_generation_and_result(
                existing,
                expected_task_generation_id,
                expected_result_report_sha256,
                expected_result_report_size_bytes,
                expected_result_input_fingerprint,
            )
            return existing
        with self._connect() as conn:
            row = conn.execute(
                """update labor_jobs set status='succeeded', finished_at=now(), retryable=false,
                       lease_expires_at=null, updated_at=now()
                   where id=%s and status='running' and worker_id=%s
                     and metadata_snapshot->>'ownerUserId'=%s
                     and coalesce(metadata_snapshot->>'taskGenerationId','')=%s
                     and coalesce(metadata_snapshot->>'resultAcceptedAt','')<>''
                     and coalesce(metadata_snapshot->>'resultAcceptedGenerationId','')=%s
                     and coalesce(metadata_snapshot->>'resultAcceptedReportSha256','')=%s
                     and coalesce((metadata_snapshot->>'resultAcceptedReportSizeBytes')::bigint,0)=%s
                     and coalesce(metadata_snapshot->>'resultAcceptedInputFingerprint','')=%s
                     and lease_expires_at > now()
                   returning *""",
                (
                    job_id,
                    device,
                    owner,
                    str(expected_task_generation_id or "").strip(),
                    str(expected_task_generation_id or "").strip(),
                    str(expected_result_report_sha256 or "").strip().lower(),
                    int(expected_result_report_size_bytes or 0),
                    str(expected_result_input_fingerprint or "").strip().lower(),
                ),
            ).fetchone()
            conn.commit()
        return self._leased_row(row)

    def complete_preflight(
        self,
        job_id: str,
        owner: str,
        device: str,
        expected_task_generation_id: str = "",
    ) -> dict[str, Any]:
        existing = self.get(job_id)
        if existing["jobType"] != "mapping_preflight":
            raise PermissionError("正式核对任务不能使用字段预检完成通道。")
        generation = str(expected_task_generation_id or "").strip()
        if existing["status"] == "succeeded":
            if (
                existing["ownerUserId"] != owner
                or existing["claimedDeviceId"] != device
                or existing["taskGenerationId"] != generation
            ):
                raise PermissionError("任务不属于当前 Worker，或任务代次已经失效。")
            return existing
        with self._connect() as conn:
            row = conn.execute(
                """update labor_jobs set status='succeeded', finished_at=now(), retryable=false,
                       lease_expires_at=null, updated_at=now()
                   where id=%s and job_type='mapping_preflight' and status='running' and worker_id=%s
                     and metadata_snapshot->>'ownerUserId'=%s
                     and coalesce(metadata_snapshot->>'taskGenerationId','')=%s
                     and lease_expires_at > now()
                   returning *""",
                (job_id, device, owner, generation),
            ).fetchone()
            conn.commit()
        return self._leased_row(row)

    def fail(
        self,
        job_id: str,
        owner: str,
        device: str,
        error_code: str,
        error_message: str,
        retryable: bool,
        retry_delay_seconds: int,
        expected_task_generation_id: str = "",
    ) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """update labor_jobs set
                       status=case when %s and attempt < max_attempts then 'retry_wait' else 'failed' end,
                       available_at=case when %s and attempt < max_attempts
                           then now()+(%s*interval '1 second') else available_at end,
                       error_code=%s, error_detail=%s,
                       retryable=(%s and attempt < max_attempts),
                       finished_at=case when %s and attempt < max_attempts then null else now() end,
                       lease_expires_at=null, updated_at=now(),
                       metadata_snapshot=metadata_snapshot
                           - 'resultAcceptedAt' - 'resultAcceptedGenerationId'
                           - 'resultAcceptedReportSha256' - 'resultAcceptedReportSizeBytes'
                           - 'resultAcceptedInputFingerprint'
                   where id=%s and status='running' and worker_id=%s
                     and metadata_snapshot->>'ownerUserId'=%s
                     and coalesce(metadata_snapshot->>'taskGenerationId','')=%s
                     and lease_expires_at > now()
                   returning *""",
                (
                    retryable, retryable, max(0, int(retry_delay_seconds)), str(error_code)[:80],
                    str(error_message)[:500], retryable, retryable, job_id, device, owner,
                    str(expected_task_generation_id or "").strip(),
                ),
            ).fetchone()
            conn.commit()
        return self._leased_row(row)

    def mark_result_accepted(
        self,
        job_id: str,
        owner: str,
        device: str,
        expected_task_generation_id: str = "",
        result_report_sha256: str = "",
        result_report_size_bytes: int = 0,
        result_input_fingerprint: str = "",
    ) -> dict[str, Any]:
        generation = str(expected_task_generation_id or "").strip()
        acceptance = json.dumps(
            {
                "resultAcceptedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "resultAcceptedGenerationId": generation,
                "resultAcceptedReportSha256": str(result_report_sha256 or "").strip().lower(),
                "resultAcceptedReportSizeBytes": int(result_report_size_bytes or 0),
                "resultAcceptedInputFingerprint": str(result_input_fingerprint or "").strip().lower(),
            },
            ensure_ascii=False,
        )
        with self._connect() as conn:
            row = conn.execute(
                """update labor_jobs set
                       metadata_snapshot=metadata_snapshot || %s::jsonb, updated_at=now()
                   where id=%s and status='running' and worker_id=%s
                     and metadata_snapshot->>'ownerUserId'=%s
                     and coalesce(metadata_snapshot->>'taskGenerationId','')=%s
                     and lease_expires_at > now()
                   returning *""",
                (acceptance, job_id, device, owner, generation),
            ).fetchone()
            conn.commit()
        return self._leased_row(row)

    def clear_result_acceptance(
        self,
        job_id: str,
        owner: str,
        device: str,
        expected_task_generation_id: str = "",
    ) -> dict[str, Any]:
        generation = str(expected_task_generation_id or "").strip()
        with self._connect() as conn:
            row = conn.execute(
                """update labor_jobs set
                       metadata_snapshot=metadata_snapshot
                           - 'resultAcceptedAt' - 'resultAcceptedGenerationId'
                           - 'resultAcceptedReportSha256' - 'resultAcceptedReportSizeBytes'
                           - 'resultAcceptedInputFingerprint',
                       updated_at=now()
                   where id=%s and status='running' and worker_id=%s
                     and metadata_snapshot->>'ownerUserId'=%s
                     and coalesce(metadata_snapshot->>'taskGenerationId','')=%s
                     and lease_expires_at > now()
                   returning *""",
                (job_id, device, owner, generation),
            ).fetchone()
            conn.commit()
        return self._leased_row(row)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("select * from labor_jobs where id=%s", (job_id,)).fetchone()
        if not row:
            raise FileNotFoundError("海外劳务 Worker 任务不存在。")
        return self._row(dict(row))

    def list(self, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("select * from labor_jobs order by updated_at desc limit %s", (max(1, limit),)).fetchall()
        return [self._row(dict(row)) for row in rows]

    def _leased_row(self, row: Any) -> dict[str, Any]:
        if not row:
            raise PermissionError("任务不属于当前 Worker，或租约已经失效。")
        return self._row(dict(row))

    def _connect(self):
        if self._connect_override:
            return self._connect_override()
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Postgres Worker 队列需要安装 psycopg[binary]。") from exc
        return psycopg.connect(
            self.database_url,
            row_factory=dict_row,
            prepare_threshold=None,
        )

    @staticmethod
    def _row(row: dict[str, Any]) -> dict[str, Any]:
        metadata = row.get("metadata_snapshot")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        metadata = metadata if isinstance(metadata, dict) else {}

        def stamp(name: str) -> str:
            value = row.get(name)
            if hasattr(value, "isoformat"):
                return value.isoformat(timespec="seconds") + "Z"
            return str(value or "")

        return {
            "id": str(row.get("id") or ""),
            "runId": str(row.get("run_id") or ""),
            "jobType": str(row.get("job_type") or "reconcile"),
            "ownerUserId": str(metadata.get("ownerUserId") or ""),
            "status": str(row.get("status") or "queued"),
            "attempt": int(row.get("attempt") or 0),
            "maxAttempts": int(row.get("max_attempts") or 3),
            "availableAt": stamp("available_at"),
            "claimedDeviceId": str(row.get("worker_id") or ""),
            "leaseExpiresAt": stamp("lease_expires_at"),
            "heartbeatAt": stamp("heartbeat_at"),
            "requiredWorkerVersion": str(metadata.get("requiredWorkerVersion") or ""),
            "taskGenerationId": str(metadata.get("taskGenerationId") or ""),
            "progress": metadata.get("progress") or {},
            "resultAcceptedAt": str(metadata.get("resultAcceptedAt") or ""),
            "resultAcceptedGenerationId": str(metadata.get("resultAcceptedGenerationId") or ""),
            "resultAcceptedReportSha256": str(metadata.get("resultAcceptedReportSha256") or ""),
            "resultAcceptedReportSizeBytes": int(metadata.get("resultAcceptedReportSizeBytes") or 0),
            "resultAcceptedInputFingerprint": str(metadata.get("resultAcceptedInputFingerprint") or ""),
            "errorCode": str(row.get("error_code") or ""),
            "errorMessage": str(row.get("error_detail") or ""),
            "createdAt": stamp("created_at"),
            "updatedAt": stamp("updated_at"),
            "startedAt": stamp("started_at"),
            "finishedAt": stamp("finished_at"),
        }

    @staticmethod
    def _assert_generation_and_result(
        job: dict[str, Any],
        expected_task_generation_id: str,
        expected_result_report_sha256: str,
        expected_result_report_size_bytes: int,
        expected_result_input_fingerprint: str,
    ) -> None:
        generation = str(expected_task_generation_id or "").strip()
        if str(job.get("taskGenerationId") or "").strip() != generation:
            raise PermissionError("Worker 任务代次已失效，不能修改当前批次。")
        if (
            not str(job.get("resultAcceptedAt") or "").strip()
            or str(job.get("resultAcceptedGenerationId") or "").strip() != generation
            or str(job.get("resultAcceptedReportSha256") or "").strip().lower()
            != str(expected_result_report_sha256 or "").strip().lower()
            or int(job.get("resultAcceptedReportSizeBytes") or 0) != int(expected_result_report_size_bytes or 0)
            or str(job.get("resultAcceptedInputFingerprint") or "").strip().lower()
            != str(expected_result_input_fingerprint or "").strip().lower()
        ):
            raise PermissionError("Worker 正式结果尚未通过服务端完整性校验，不能完成任务。")


def _version_code(value: str) -> int:
    return 0 if not str(value or "").strip() else worker_version_code(value)


def _job_type(value: str) -> str:
    normalized = str(value or "reconcile").strip().lower()
    if normalized not in {"reconcile", "mapping_preflight"}:
        raise PermissionError("未知的海外劳务 Worker 任务类型。")
    return normalized
