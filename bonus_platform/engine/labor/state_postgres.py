from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping


P1_STATE_TABLES = {
    "runs": "labor_runs",
    "files": "labor_run_files",
    "mappings": "labor_workbook_mappings",
    "reviews": "labor_business_reviews",
    "devices": "labor_worker_devices",
    "tokens": "labor_worker_tokens",
    "audit": "labor_audit_events",
    "jobs": "labor_jobs",
    "schema_versions": "labor_schema_versions",
}
P1_SCHEMA_VERSION = 1


class LaborStateError(RuntimeError):
    pass


class LaborStateNotFound(FileNotFoundError, LaborStateError):
    pass


class LaborStateOwnerMismatch(PermissionError, LaborStateError):
    pass


class LaborStateConflict(LaborStateError):
    pass


def labor_state_backend(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    return str(source.get("SIGMA_LABOR_STATE_BACKEND") or "local").strip().lower()


def labor_state_database_url(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    return str(
        source.get("SIGMA_LABOR_DATABASE_URL")
        or source.get("ADMIN_DATABASE_URL")
        or ""
    ).strip()


def labor_postgres_state_enabled(env: Mapping[str, str] | None = None) -> bool:
    return labor_state_backend(env) == "postgres" and bool(labor_state_database_url(env))


def labor_postgres_state_health(
    *,
    env: Mapping[str, str] | None = None,
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    backend = labor_state_backend(env)
    configured = backend == "postgres" and bool(labor_state_database_url(env))
    if not configured:
        return {
            "backend": backend,
            "configured": False,
            "ready": False,
            "missingTables": list(P1_STATE_TABLES.values()),
            "schemaVersion": 0,
            "requiredSchemaVersion": P1_SCHEMA_VERSION,
        }
    aliases = [f"{key}_ready" for key in P1_STATE_TABLES]
    expressions = [
        f"to_regclass('public.{table}') is not null as {alias}"
        for alias, table in zip(aliases, P1_STATE_TABLES.values())
    ]
    try:
        with _open_connection(env=env, connect=connect) as connection:
            row = connection.execute(f"select {', '.join(expressions)}").fetchone()
            values = dict(row or {})
            missing = [
                table
                for alias, table in zip(aliases, P1_STATE_TABLES.values())
                if not bool(values.get(alias))
            ]
            schema_version = 0
            if "labor_schema_versions" not in missing:
                version_row = connection.execute(
                    "select version from public.labor_schema_versions where component='labor_p1'"
                ).fetchone()
                schema_version = int((version_row or {}).get("version") or 0)
        return {
            "backend": "postgres",
            "configured": True,
            "ready": not missing and schema_version >= P1_SCHEMA_VERSION,
            "missingTables": missing,
            "schemaVersion": schema_version,
            "requiredSchemaVersion": P1_SCHEMA_VERSION,
        }
    except Exception as exc:  # noqa: BLE001 - readiness must stay sanitized.
        return {
            "backend": "postgres",
            "configured": True,
            "ready": False,
            "missingTables": list(P1_STATE_TABLES.values()),
            "schemaVersion": 0,
            "requiredSchemaVersion": P1_SCHEMA_VERSION,
            "error": _safe_error(exc),
        }


def create_labor_run_state(
    metadata: Mapping[str, Any],
    *,
    actor_user_id: str = "",
    idempotency_key: str = "",
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    payload = _normalized_snapshot(metadata)
    run_id = _required(payload.get("id"), "run_id")
    owner_user_id = _required(payload.get("ownerUserId"), "owner_user_id")
    actor = _required(actor_user_id or owner_user_id, "actor_user_id")
    idempotency = str(idempotency_key or "").strip() or None
    now = _utc_iso()
    payload.setdefault("createdAt", now)
    payload["updatedAt"] = now
    payload["ownerUserId"] = owner_user_id
    payload["id"] = run_id

    with _open_connection(connect=connect) as connection:
        try:
            if idempotency:
                existing = connection.execute(
                    """
                    select * from public.labor_runs
                    where owner_user_id=%s and idempotency_key=%s and deleted_at is null
                    for update
                    """,
                    (owner_user_id, idempotency),
                ).fetchone()
                if existing:
                    connection.commit()
                    return _snapshot_from_row(existing)
            row = connection.execute(
                """
                insert into public.labor_runs (
                    id, owner_user_id, revision, status, supplier_name,
                    period_start, period_end, currency, idempotency_key,
                    metadata_snapshot, created_at, updated_at
                ) values (
                    %s, %s, 1, %s, %s,
                    nullif(%s, '')::date, nullif(%s, '')::date, %s, %s,
                    %s::jsonb, now(), now()
                )
                returning *
                """,
                (
                    run_id,
                    owner_user_id,
                    str(payload.get("status") or "已创建"),
                    str(payload.get("supplierName") or ""),
                    str(payload.get("periodStart") or ""),
                    str(payload.get("periodEnd") or ""),
                    str(payload.get("currency") or "USD"),
                    idempotency,
                    _json(payload),
                ),
            ).fetchone()
            if not row:
                raise LaborStateConflict("Postgres 未返回新建批次。")
            _sync_derived_state(connection, {}, payload, run_id, owner_user_id, actor, 1)
            _insert_audit(
                connection,
                run_id=run_id,
                owner_user_id=owner_user_id,
                actor_user_id=actor,
                action="run_created",
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return _snapshot_from_row(row)


def load_labor_run_state(
    run_id: str,
    *,
    include_deleted: bool = False,
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    safe_run_id = _required(run_id, "run_id")
    deleted_clause = "" if include_deleted else "and deleted_at is null"
    with _open_connection(connect=connect) as connection:
        row = connection.execute(
            f"select * from public.labor_runs where id=%s {deleted_clause}",
            (safe_run_id,),
        ).fetchone()
    if not row:
        raise LaborStateNotFound("劳务核对批次不存在。")
    return _snapshot_from_row(row)


def list_labor_run_states(
    *,
    owner_user_id: str = "",
    limit: int = 200,
    connect: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(int(limit or 200), 500))
    owner = str(owner_user_id or "").strip()
    if owner:
        sql = """
            select * from public.labor_runs
            where owner_user_id=%s and deleted_at is null
            order by updated_at desc limit %s
        """
        params = (owner, bounded_limit)
    else:
        sql = """
            select * from public.labor_runs
            where deleted_at is null
            order by updated_at desc limit %s
        """
        params = (bounded_limit,)
    with _open_connection(connect=connect) as connection:
        rows = connection.execute(sql, params).fetchall()
    return [_snapshot_from_row(row) for row in rows]


def transition_labor_run_state(
    run_id: str,
    transition: Callable[[dict[str, Any]], Mapping[str, Any] | None],
    *,
    actor_user_id: str = "",
    action: str = "",
    outcome: str = "success",
    reason_code: str = "",
    audit_details: Mapping[str, Any] | None = None,
    connect: Callable[[], Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    safe_run_id = _required(run_id, "run_id")
    with _open_connection(connect=connect) as connection:
        try:
            row = connection.execute(
                """
                select * from public.labor_runs
                where id=%s and deleted_at is null
                for update
                """,
                (safe_run_id,),
            ).fetchone()
            if not row:
                raise LaborStateNotFound("劳务核对批次不存在。")
            before = _snapshot_from_row(row)
            owner = _required(before.get("ownerUserId"), "owner_user_id")
            actor = _required(actor_user_id or owner, "actor_user_id")
            proposed = transition(dict(before))
            if proposed is None:
                connection.commit()
                return before, False
            after = _normalized_snapshot(proposed)
            if _required(after.get("id"), "run_id") != safe_run_id:
                raise LaborStateConflict("批次 ID 不允许修改。")
            if _required(after.get("ownerUserId"), "owner_user_id") != owner:
                raise LaborStateOwnerMismatch("批次 owner 只能来自服务端认证上下文，且不允许修改。")
            old_revision = int(before.get("stateRevision") or row.get("revision") or 1)
            after.pop("stateRevision", None)
            after["createdAt"] = str(before.get("createdAt") or after.get("createdAt") or _utc_iso())
            after["updatedAt"] = _utc_iso()
            updated_row = connection.execute(
                """
                update public.labor_runs
                set revision=revision+1,
                    status=%s,
                    supplier_name=%s,
                    period_start=nullif(%s, '')::date,
                    period_end=nullif(%s, '')::date,
                    currency=%s,
                    metadata_snapshot=%s::jsonb,
                    updated_at=now()
                where id=%s and revision=%s and deleted_at is null
                returning *
                """,
                (
                    str(after.get("status") or "已创建"),
                    str(after.get("supplierName") or ""),
                    str(after.get("periodStart") or ""),
                    str(after.get("periodEnd") or ""),
                    str(after.get("currency") or "USD"),
                    _json(after),
                    safe_run_id,
                    old_revision,
                ),
            ).fetchone()
            if not updated_row:
                raise LaborStateConflict("批次已被其他请求更新，请刷新后重试。")
            next_revision = old_revision + 1
            _sync_derived_state(connection, before, after, safe_run_id, owner, actor, next_revision)
            if action:
                _insert_audit(
                    connection,
                    run_id=safe_run_id,
                    owner_user_id=owner,
                    actor_user_id=actor,
                    action=action,
                    outcome=outcome,
                    reason_code=reason_code,
                    details=audit_details,
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return _snapshot_from_row(updated_row), True


def soft_delete_labor_run_state(
    run_id: str,
    *,
    actor_user_id: str,
    reason_code: str,
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    safe_run_id = _required(run_id, "run_id")
    with _open_connection(connect=connect) as connection:
        try:
            row = connection.execute(
                """
                select * from public.labor_runs
                where id=%s and deleted_at is null
                for update
                """,
                (safe_run_id,),
            ).fetchone()
            if not row:
                raise LaborStateNotFound("劳务核对批次不存在。")
            snapshot = _snapshot_from_row(row)
            owner = _required(snapshot.get("ownerUserId"), "owner_user_id")
            actor = _required(actor_user_id, "actor_user_id")
            connection.execute(
                """
                update public.labor_runs
                set deleted_at=now(), status='已删除', revision=revision+1, updated_at=now()
                where id=%s and deleted_at is null
                """,
                (safe_run_id,),
            )
            _insert_audit(
                connection,
                run_id=safe_run_id,
                owner_user_id=owner,
                actor_user_id=actor,
                action="run_deleted",
                reason_code=reason_code,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return snapshot


def create_pending_labor_file_state(
    *,
    run_id: str,
    owner_user_id: str,
    actor_user_id: str,
    file_id: str,
    file_kind: str,
    object_key: str,
    original_filename: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    return create_pending_labor_file_states(
        run_id=run_id,
        owner_user_id=owner_user_id,
        actor_user_id=actor_user_id,
        files=[
            {
                "file_id": file_id,
                "file_kind": file_kind,
                "object_key": object_key,
                "original_filename": original_filename,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "sha256": sha256,
            }
        ],
        connect=connect,
    )[0]


def create_pending_labor_file_states(
    *,
    run_id: str,
    owner_user_id: str,
    actor_user_id: str,
    files: list[Mapping[str, Any]],
    max_files_by_kind: Mapping[str, int] | None = None,
    connect: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    """Create one upload batch atomically while holding the owned run lock."""
    safe_run_id = _required(run_id, "run_id")
    owner = _required(owner_user_id, "owner_user_id")
    actor = _required(actor_user_id, "actor_user_id")
    if not isinstance(files, list) or not files:
        raise ValueError("files must contain at least one upload record")
    if len(files) > 64:
        raise ValueError("upload batch is too large")
    normalized = []
    requested_counts: dict[str, int] = {}
    for raw in files:
        if not isinstance(raw, Mapping):
            raise ValueError("upload file record must be a mapping")
        safe_size = int(raw.get("size_bytes") or 0)
        if safe_size <= 0:
            raise ValueError("size_bytes must be positive")
        file_kind = _required(raw.get("file_kind"), "file_kind")
        normalized.append(
            {
                "file_id": _required(raw.get("file_id"), "file_id"),
                "file_kind": file_kind,
                "object_key": _required(raw.get("object_key"), "object_key"),
                "original_filename": str(raw.get("original_filename") or "")[:255],
                "content_type": str(raw.get("content_type") or "application/octet-stream")[:160],
                "size_bytes": safe_size,
                "sha256": _validated_sha256(raw.get("sha256")),
            }
        )
        requested_counts[file_kind] = requested_counts.get(file_kind, 0) + 1
    limits = {
        str(kind): max(0, int(limit))
        for kind, limit in dict(max_files_by_kind or {}).items()
    }
    with _open_connection(connect=connect) as connection:
        try:
            _lock_owned_run(connection, safe_run_id, owner)
            superseded = connection.execute(
                """
                update public.labor_run_files
                set upload_state='rejected', updated_at=now()
                where run_id=%s and owner_user_id=%s and deleted_at is null
                  and upload_state='pending'
                returning id
                """,
                (safe_run_id, owner),
            ).fetchall()
            if superseded:
                _insert_audit(
                    connection,
                    run_id=safe_run_id,
                    owner_user_id=owner,
                    actor_user_id=actor,
                    action="file_upload_intents_superseded",
                    reason_code="new_upload_batch_started",
                    details={"fileIds": [str(item.get("id") or "") for item in superseded[:64]]},
                )
            if limits:
                existing_rows = connection.execute(
                    """
                    select file_kind, count(*)::bigint as active_count
                    from public.labor_run_files
                    where run_id=%s and owner_user_id=%s and deleted_at is null
                      and upload_state in ('pending', 'ready')
                    group by file_kind
                    """,
                    (safe_run_id, owner),
                ).fetchall()
                existing_counts = {
                    str(item.get("file_kind") or ""): int(item.get("active_count") or 0)
                    for item in existing_rows
                }
                for file_kind, requested in requested_counts.items():
                    limit = limits.get(file_kind)
                    if limit is not None and existing_counts.get(file_kind, 0) + requested > limit:
                        label = "PDF" if file_kind == "pdf_invoice" else "Excel"
                        raise LaborStateConflict(f"{label} 文件数量已达到上限 {limit}。")
            rows = []
            for item in normalized:
                row = connection.execute(
                    """
                    insert into public.labor_run_files (
                        id, run_id, owner_user_id, file_kind, object_key,
                        original_filename, content_type, size_bytes, sha256,
                        upload_state, created_at, updated_at
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', now(), now())
                    returning *
                    """,
                    (
                        item["file_id"],
                        safe_run_id,
                        owner,
                        item["file_kind"],
                        item["object_key"],
                        item["original_filename"],
                        item["content_type"],
                        item["size_bytes"],
                        item["sha256"],
                    ),
                ).fetchone()
                if not row:
                    raise LaborStateConflict("文件上传意图未写入状态库。")
                rows.append(row)
                _insert_audit(
                    connection,
                    run_id=safe_run_id,
                    owner_user_id=owner,
                    actor_user_id=actor,
                    action="file_upload_intent_created",
                    details={
                        "fileId": item["file_id"],
                        "fileKind": item["file_kind"],
                        "sizeBytes": item["size_bytes"],
                    },
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return [_file_from_row(row) for row in rows]


def finalize_labor_file_state(
    *,
    run_id: str,
    owner_user_id: str,
    actor_user_id: str,
    file_id: str,
    observed_size_bytes: int,
    reported_sha256: str,
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    safe_run_id = _required(run_id, "run_id")
    owner = _required(owner_user_id, "owner_user_id")
    actor = _required(actor_user_id, "actor_user_id")
    safe_file_id = _required(file_id, "file_id")
    observed_size = int(observed_size_bytes or 0)
    digest = _validated_sha256(reported_sha256)
    with _open_connection(connect=connect) as connection:
        try:
            run_row = _lock_owned_run(connection, safe_run_id, owner)
            file_row = connection.execute(
                """
                select * from public.labor_run_files
                where id=%s and run_id=%s and owner_user_id=%s and deleted_at is null
                for update
                """,
                (safe_file_id, safe_run_id, owner),
            ).fetchone()
            if not file_row:
                raise LaborStateNotFound("上传文件记录不存在。")
            file_values = dict(file_row)
            expected_size = int(file_values.get("size_bytes") or 0)
            expected_digest = str(file_values.get("sha256") or "").strip().lower()
            if observed_size != expected_size or digest != expected_digest:
                raise LaborStateConflict("对象存储文件大小或 SHA-256 与上传意图不一致。")
            if str(file_values.get("upload_state") or "") == "ready":
                connection.commit()
                return _file_from_row(file_values)
            row = connection.execute(
                """
                update public.labor_run_files
                set upload_state='ready', updated_at=now()
                where id=%s and run_id=%s and owner_user_id=%s and upload_state='pending' and deleted_at is null
                returning *
                """,
                (safe_file_id, safe_run_id, owner),
            ).fetchone()
            if not row:
                raise LaborStateConflict("文件上传状态已变化，请刷新后重试。")
            ready_rows = connection.execute(
                """
                select * from public.labor_run_files
                where run_id=%s and owner_user_id=%s
                  and upload_state='ready' and deleted_at is null
                order by created_at, id
                """,
                (safe_run_id, owner),
            ).fetchall()
            snapshot = _snapshot_from_row(run_row)
            snapshot.pop("stateRevision", None)
            files = dict(snapshot.get("files") or {})
            ready_files = [_file_from_row(item) for item in ready_rows]
            public_records = [_labor_file_snapshot_record(item) for item in ready_files]
            pdf_records = [item for item in public_records if item.get("fileKind") == "pdf_invoice"]
            workbook_records = [item for item in public_records if item.get("fileKind") == "workbook"]
            files["pdfInvoices"] = pdf_records
            files["workbooks"] = workbook_records
            if workbook_records:
                files["workbook"] = workbook_records[0]
            else:
                files.pop("workbook", None)
            snapshot.update(
                {
                    "status": "已上传文件",
                    "stage": "文件已进入私有存储",
                    "files": files,
                    "updatedAt": _utc_iso(),
                    "machineCheckStatus": "needs_review",
                    "businessReviewStatus": "pending",
                    "manualReviewRequired": True,
                    "directPaymentAllowed": False,
                    "requiresHumanReview": True,
                    "resultInputFingerprint": "",
                    "diffDownloadUrl": "",
                    "businessReportDownloadUrl": "",
                }
            )
            old_revision = int(run_row.get("revision") or 1)
            updated_run = connection.execute(
                """
                update public.labor_runs
                set status=%s, metadata_snapshot=%s::jsonb,
                    revision=revision+1, updated_at=now()
                where id=%s and owner_user_id=%s and revision=%s and deleted_at is null
                returning *
                """,
                (snapshot["status"], _json(snapshot), safe_run_id, owner, old_revision),
            ).fetchone()
            if not updated_run:
                raise LaborStateConflict("批次文件清单已被其他请求更新，请刷新后重试。")
            _insert_audit(
                connection,
                run_id=safe_run_id,
                owner_user_id=owner,
                actor_user_id=actor,
                action="file_upload_finalized",
                details={"fileId": safe_file_id, "sizeBytes": observed_size, "sha256": digest},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return _file_from_row(row)


def _labor_file_snapshot_record(file_state: Mapping[str, Any]) -> dict[str, Any]:
    filename = str(file_state.get("originalFilename") or "")
    return {
        "id": str(file_state.get("id") or ""),
        "fileKind": str(file_state.get("fileKind") or ""),
        "filename": filename,
        "originalFilename": filename,
        "objectKey": str(file_state.get("objectKey") or ""),
        "contentType": str(file_state.get("contentType") or "application/octet-stream"),
        "sizeBytes": int(file_state.get("sizeBytes") or 0),
        "sha256": str(file_state.get("sha256") or ""),
        "uploadState": str(file_state.get("uploadState") or ""),
        "storageBackend": "supabase",
    }


def get_labor_file_state(
    *,
    run_id: str,
    owner_user_id: str,
    file_id: str,
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    with _open_connection(connect=connect) as connection:
        row = connection.execute(
            """
            select * from public.labor_run_files
            where id=%s and run_id=%s and owner_user_id=%s and deleted_at is null
            """,
            (_required(file_id, "file_id"), _required(run_id, "run_id"), _required(owner_user_id, "owner_user_id")),
        ).fetchone()
    if not row:
        raise LaborStateNotFound("上传文件记录不存在。")
    return _file_from_row(row)


def list_labor_file_states(
    *,
    run_id: str,
    owner_user_id: str,
    ready_only: bool = False,
    connect: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    ready_clause = "and upload_state='ready'" if ready_only else ""
    with _open_connection(connect=connect) as connection:
        rows = connection.execute(
            f"""
            select * from public.labor_run_files
            where run_id=%s and owner_user_id=%s and deleted_at is null {ready_clause}
            order by created_at, id
            """,
            (_required(run_id, "run_id"), _required(owner_user_id, "owner_user_id")),
        ).fetchall()
    return [_file_from_row(row) for row in rows]


def append_labor_audit_event_state(
    *,
    action: str,
    run_id: str = "",
    owner_user_id: str,
    actor_user_id: str,
    outcome: str = "success",
    reason_code: str = "",
    details: Mapping[str, Any] | None = None,
    connect: Callable[[], Any] | None = None,
) -> None:
    with _open_connection(connect=connect) as connection:
        try:
            _insert_audit(
                connection,
                run_id=str(run_id or "").strip(),
                owner_user_id=_required(owner_user_id, "owner_user_id"),
                actor_user_id=_required(actor_user_id, "actor_user_id"),
                action=_required(action, "action"),
                outcome=outcome,
                reason_code=reason_code,
                details=details,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def read_labor_audit_events_state(
    *,
    owner_user_id: str = "",
    run_id: str = "",
    limit: int = 200,
    connect: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if str(owner_user_id or "").strip():
        clauses.append("owner_user_id=%s")
        params.append(str(owner_user_id).strip())
    if str(run_id or "").strip():
        clauses.append("run_id=%s")
        params.append(str(run_id).strip())
    where = f"where {' and '.join(clauses)}" if clauses else ""
    params.append(max(1, min(int(limit or 200), 500)))
    with _open_connection(connect=connect) as connection:
        rows = connection.execute(
            f"""
            select * from public.labor_audit_events
            {where}
            order by created_at desc
            limit %s
            """,
            tuple(params),
        ).fetchall()
    return [_audit_from_row(row) for row in reversed(rows)]


def _sync_derived_state(
    connection: Any,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    run_id: str,
    owner_user_id: str,
    actor_user_id: str,
    revision: int,
) -> None:
    if _input_file_manifest(before.get("files")) != _input_file_manifest(after.get("files")):
        _replace_file_manifest(connection, run_id, owner_user_id, after.get("files"))
    mapping_before = (
        before.get("workbookSheet"),
        before.get("excelMapping"),
        before.get("manualNameMapping"),
    )
    mapping_after = (
        after.get("workbookSheet"),
        after.get("excelMapping"),
        after.get("manualNameMapping"),
    )
    if mapping_before != mapping_after and isinstance(after.get("excelMapping"), dict):
        connection.execute(
            """
            insert into public.labor_workbook_mappings (
                run_id, owner_user_id, version, sheet_name, mapping,
                manual_name_mapping, input_fingerprint, actor_user_id, created_at
            )
            select %s, %s, coalesce(max(version), 0) + 1, %s, %s::jsonb,
                   %s::jsonb, %s, %s, now()
            from public.labor_workbook_mappings
            where run_id=%s
            """,
            (
                run_id,
                owner_user_id,
                str(after.get("workbookSheet") or ""),
                _json(after.get("excelMapping") or {}),
                _json(after.get("manualNameMapping") or {}),
                str(after.get("inputFingerprint") or after.get("resultInputFingerprint") or ""),
                actor_user_id,
                run_id,
            ),
        )
    before_review = (
        str(before.get("businessReviewStatus") or "pending"),
        str(before.get("businessReviewReason") or ""),
        str(before.get("businessReviewedBy") or ""),
        str(before.get("businessReviewedAt") or ""),
        str(before.get("resultInputFingerprint") or ""),
    )
    after_review = (
        str(after.get("businessReviewStatus") or "pending"),
        str(after.get("businessReviewReason") or ""),
        str(after.get("businessReviewedBy") or ""),
        str(after.get("businessReviewedAt") or ""),
        str(after.get("resultInputFingerprint") or ""),
    )
    if before_review != after_review:
        connection.execute(
            """
            insert into public.labor_business_reviews (
                run_id, owner_user_id, reviewer_user_id, decision, reason,
                result_input_fingerprint, run_revision, created_at
            ) values (%s, %s, %s, %s, %s, %s, %s, now())
            """,
            (
                run_id,
                owner_user_id,
                actor_user_id,
                after_review[0],
                str(after.get("businessReviewReason") or ""),
                str(after.get("resultInputFingerprint") or ""),
                int(revision),
            ),
        )


def _replace_file_manifest(connection: Any, run_id: str, owner_user_id: str, files: Any) -> None:
    connection.execute(
        "update public.labor_run_files set deleted_at=now(), upload_state='deleted', updated_at=now() where run_id=%s and deleted_at is null",
        (run_id,),
    )
    for kind, record in _iter_input_file_records(files):
        object_key = str(record.get("objectKey") or record.get("blobPath") or record.get("path") or "").strip()
        filename = Path(str(record.get("originalFilename") or record.get("filename") or object_key)).name
        if not object_key and filename:
            object_key = f"unresolved/{run_id}/{filename}"
        if not object_key:
            continue
        file_id = "labor_file_" + hashlib.sha256(f"{run_id}\0{kind}\0{object_key}".encode("utf-8")).hexdigest()[:24]
        connection.execute(
            """
            insert into public.labor_run_files (
                id, run_id, owner_user_id, file_kind, object_key,
                original_filename, content_type, size_bytes, sha256,
                upload_state, created_at, updated_at, deleted_at
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'ready', now(), now(), null)
            on conflict (run_id, object_key) do update set
                owner_user_id=excluded.owner_user_id,
                file_kind=excluded.file_kind,
                original_filename=excluded.original_filename,
                content_type=excluded.content_type,
                size_bytes=excluded.size_bytes,
                sha256=excluded.sha256,
                upload_state='ready',
                updated_at=now(),
                deleted_at=null
            """,
            (
                file_id,
                run_id,
                owner_user_id,
                kind,
                object_key,
                filename,
                str(record.get("contentType") or record.get("content_type") or "application/octet-stream"),
                max(0, int(record.get("sizeBytes") or record.get("size_bytes") or 0)),
                str(record.get("sha256") or "").strip().lower(),
            ),
        )


def _input_file_manifest(files: Any) -> dict[str, list[dict[str, Any]]]:
    manifest: dict[str, list[dict[str, Any]]] = {"pdf_invoice": [], "workbook": []}
    for kind, record in _iter_input_file_records(files):
        manifest[kind].append(dict(record))
    return manifest


def _iter_input_file_records(files: Any):
    if not isinstance(files, dict):
        return
    pdf_records = files.get("pdfInvoices") if isinstance(files.get("pdfInvoices"), list) else []
    workbook_records = files.get("workbooks") if isinstance(files.get("workbooks"), list) else []
    if not workbook_records and isinstance(files.get("workbook"), dict):
        workbook_records = [files["workbook"]]
    for record in pdf_records:
        if isinstance(record, dict):
            yield "pdf_invoice", record
    for record in workbook_records:
        if isinstance(record, dict):
            yield "workbook", record


def _insert_audit(
    connection: Any,
    *,
    run_id: str,
    owner_user_id: str,
    actor_user_id: str,
    action: str,
    outcome: str = "success",
    reason_code: str = "",
    details: Mapping[str, Any] | None = None,
) -> None:
    connection.execute(
        """
        insert into public.labor_audit_events (
            run_id, owner_user_id, actor_user_id, action,
            outcome, reason_code, details, created_at
        ) values (nullif(%s, ''), %s, %s, %s, %s, %s, %s::jsonb, now())
        """,
        (
            str(run_id or "").strip(),
            _required(owner_user_id, "owner_user_id"),
            _required(actor_user_id, "actor_user_id"),
            _required(action, "action"),
            str(outcome or "success")[:64],
            str(reason_code or "")[:128],
            _json(dict(details or {})),
        ),
    )


def _snapshot_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(row)
    snapshot = values.get("metadata_snapshot")
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except json.JSONDecodeError:
            snapshot = {}
    payload = dict(snapshot) if isinstance(snapshot, dict) else {}
    payload["id"] = str(values.get("id") or payload.get("id") or "")
    payload["ownerUserId"] = str(values.get("owner_user_id") or payload.get("ownerUserId") or "")
    payload["status"] = str(values.get("status") or payload.get("status") or "已创建")
    payload["stateRevision"] = int(values.get("revision") or payload.get("stateRevision") or 1)
    payload["createdAt"] = _stamp(values.get("created_at")) or str(payload.get("createdAt") or "")
    payload["updatedAt"] = _stamp(values.get("updated_at")) or str(payload.get("updatedAt") or "")
    return payload


def _audit_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(row)
    details = values.get("details")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except json.JSONDecodeError:
            details = {}
    return {
        "schemaVersion": 1,
        "createdAt": _stamp(values.get("created_at")),
        "action": str(values.get("action") or ""),
        "runId": str(values.get("run_id") or ""),
        "ownerUserId": str(values.get("owner_user_id") or ""),
        "actorUserId": str(values.get("actor_user_id") or ""),
        "outcome": str(values.get("outcome") or "success"),
        "reasonCode": str(values.get("reason_code") or ""),
        "details": details if isinstance(details, dict) else {},
    }


def _file_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(row)
    return {
        "id": str(values.get("id") or ""),
        "runId": str(values.get("run_id") or ""),
        "ownerUserId": str(values.get("owner_user_id") or ""),
        "fileKind": str(values.get("file_kind") or ""),
        "objectKey": str(values.get("object_key") or ""),
        "originalFilename": str(values.get("original_filename") or ""),
        "contentType": str(values.get("content_type") or "application/octet-stream"),
        "sizeBytes": int(values.get("size_bytes") or 0),
        "sha256": str(values.get("sha256") or ""),
        "uploadState": str(values.get("upload_state") or ""),
        "createdAt": _stamp(values.get("created_at")),
        "updatedAt": _stamp(values.get("updated_at")),
    }


def _lock_owned_run(connection: Any, run_id: str, owner_user_id: str) -> Mapping[str, Any]:
    row = connection.execute(
        """
        select * from public.labor_runs
        where id=%s and deleted_at is null
        for update
        """,
        (run_id,),
    ).fetchone()
    if not row:
        raise LaborStateNotFound("劳务核对批次不存在。")
    values = dict(row)
    if str(values.get("owner_user_id") or "") != owner_user_id:
        raise LaborStateOwnerMismatch("批次不属于当前用户。")
    return values


def _validated_sha256(value: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
    return digest


def _normalized_snapshot(metadata: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        raise TypeError("labor metadata must be a mapping")
    payload = dict(metadata)
    payload.pop("stateRevision", None)
    return payload


def _required(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    return str(value or "")


def _safe_error(exc: Exception) -> str:
    text = str(exc or exc.__class__.__name__)
    text = text.replace(labor_state_database_url(), "") if labor_state_database_url() else text
    return text.replace("\n", " ")[:240]


def _open_connection(
    *,
    env: Mapping[str, str] | None = None,
    connect: Callable[[], Any] | None = None,
):
    if connect is not None:
        return connect()
    database_url = labor_state_database_url(env)
    if not database_url:
        raise LaborStateError("未配置 SIGMA_LABOR_DATABASE_URL。")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise LaborStateError("Postgres 状态库需要安装 psycopg[binary]。") from exc
    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        prepare_threshold=None,
        connect_timeout=5,
    )
