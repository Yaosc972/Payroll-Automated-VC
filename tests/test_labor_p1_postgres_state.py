from datetime import datetime, timezone
from pathlib import Path

import pytest

from bonus_platform.engine.labor import state_postgres
import bonus_platform.engine.labor.runs as labor_runs
import bonus_platform.engine.labor.audit as labor_audit


class FakeResult:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakeConnection:
    def __init__(self, results):
        self.results = list(results)
        self.queries = []
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.queries.append((" ".join(sql.split()), params))
        result = self.results.pop(0) if self.results else FakeResult()
        if isinstance(result, Exception):
            raise result
        return result

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _state_row(*, owner="user-1", revision=1, snapshot=None):
    now = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    payload = {
        "id": "labor-1",
        "ownerUserId": owner,
        "status": "已创建",
        "supplierName": "Fixture Supplier",
        "createdAt": now.isoformat(),
        "updatedAt": now.isoformat(),
        **(snapshot or {}),
    }
    return {
        "id": "labor-1",
        "owner_user_id": owner,
        "revision": revision,
        "status": payload["status"],
        "metadata_snapshot": payload,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }


def test_p1_sql_declares_authoritative_tables_constraints_and_private_access():
    sql = Path("docs/sql/labor_p1_state.sql").read_text(encoding="utf-8").lower()

    for table in (
        "labor_runs",
        "labor_run_files",
        "labor_workbook_mappings",
        "labor_business_reviews",
        "labor_worker_devices",
        "labor_worker_tokens",
        "labor_audit_events",
        "labor_jobs",
        "labor_schema_versions",
    ):
        assert f"create table if not exists public.{table}" in sql
    assert "revision bigint not null" in sql
    assert "owner_user_id text not null" in sql
    assert "foreign key (run_id) references public.labor_runs" in sql
    assert "for update skip locked" in sql
    assert "labor_jobs_run_fk" in sql
    assert "validate constraint labor_jobs_run_fk" in sql
    assert "labor_jobs_owner_claim_idx" in sql
    assert "insert into public.labor_schema_versions" in sql
    assert "revoke all" in sql
    assert "enable row level security" in sql


def test_p1_sql_upgrades_legacy_run_and_job_owners_before_owner_scoped_indexes():
    sql = Path("docs/sql/labor_p1_state.sql").read_text(encoding="utf-8").lower()

    add_run_owner = sql.index("add column if not exists owner_user_id text;")
    backfill_run_owner = sql.index("set owner_user_id=coalesce(")
    run_owner_index = sql.index("create unique index if not exists labor_runs_owner_idempotency_idx")
    backfill_job_owner = sql.index("set metadata_snapshot=jsonb_set(")
    add_generated_job_owner = sql.index(
        "add column if not exists owner_user_id text generated always as "
        "(metadata_snapshot ->> 'owneruserid') stored;"
    )

    assert add_run_owner < backfill_run_owner < run_owner_index
    assert backfill_job_owner < add_generated_job_owner
    assert "'legacy:' || id" in sql
    assert "alter table public.labor_runs validate constraint labor_runs_owner_not_blank" in sql
    assert "alter table public.labor_jobs validate constraint labor_jobs_owner_not_blank" in sql


def test_p1_state_health_requires_every_authoritative_table():
    connection = FakeConnection(
        [
            FakeResult(
                row={
                    "runs_ready": True,
                    "files_ready": True,
                    "mappings_ready": True,
                    "reviews_ready": True,
                    "devices_ready": True,
                    "tokens_ready": True,
                    "audit_ready": True,
                    "jobs_ready": True,
                    "schema_versions_ready": True,
                }
            ),
            FakeResult(row={"version": 1}),
        ]
    )

    health = state_postgres.labor_postgres_state_health(
        env={"SIGMA_LABOR_STATE_BACKEND": "postgres", "SIGMA_LABOR_DATABASE_URL": "postgres://secret"},
        connect=lambda: connection,
    )

    assert health == {
        "backend": "postgres",
        "configured": True,
        "ready": True,
        "missingTables": [],
        "schemaVersion": 1,
        "requiredSchemaVersion": 1,
    }
    assert "secret" not in str(health)


def test_p1_state_connection_disables_prepared_statements_for_transaction_pooler(monkeypatch):
    import psycopg

    captured = {}
    connection = object()

    def fake_connect(database_url, **kwargs):
        captured["database_url"] = database_url
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(psycopg, "connect", fake_connect)

    opened = state_postgres._open_connection(
        env={"SIGMA_LABOR_DATABASE_URL": "postgres://pooler.example.invalid/database"},
    )

    assert opened is connection
    assert captured["prepare_threshold"] is None


def test_p1_state_health_rejects_legacy_tables_without_completed_schema_marker():
    connection = FakeConnection(
        [
            FakeResult(
                row={
                    "runs_ready": True,
                    "files_ready": True,
                    "mappings_ready": True,
                    "reviews_ready": True,
                    "devices_ready": True,
                    "tokens_ready": True,
                    "audit_ready": True,
                    "jobs_ready": True,
                    "schema_versions_ready": False,
                }
            )
        ]
    )

    health = state_postgres.labor_postgres_state_health(
        env={"SIGMA_LABOR_STATE_BACKEND": "postgres", "SIGMA_LABOR_DATABASE_URL": "postgres://secret"},
        connect=lambda: connection,
    )

    assert health["ready"] is False
    assert health["schemaVersion"] == 0
    assert "labor_schema_versions" in health["missingTables"]


def test_p1_create_run_binds_owner_and_writes_audit_in_one_transaction():
    row = _state_row()
    connection = FakeConnection([FakeResult(row=row), FakeResult()])

    created = state_postgres.create_labor_run_state(
        row["metadata_snapshot"],
        actor_user_id="user-1",
        connect=lambda: connection,
    )

    insert_sql, insert_params = connection.queries[0]
    audit_sql, audit_params = connection.queries[1]
    assert "insert into public.labor_runs" in insert_sql.lower()
    assert insert_params[1] == "user-1"
    assert "insert into public.labor_audit_events" in audit_sql.lower()
    assert audit_params[1:4] == ("user-1", "user-1", "run_created")
    assert created["ownerUserId"] == "user-1"
    assert created["stateRevision"] == 1
    assert connection.committed is True


def test_p1_transition_locks_run_and_rejects_owner_change():
    connection = FakeConnection([FakeResult(row=_state_row())])

    with pytest.raises(state_postgres.LaborStateOwnerMismatch):
        state_postgres.transition_labor_run_state(
            "labor-1",
            lambda snapshot: {**snapshot, "ownerUserId": "attacker"},
            connect=lambda: connection,
        )

    select_sql, _ = connection.queries[0]
    assert "for update" in select_sql.lower()
    assert connection.rolled_back is True


def test_p1_mapping_change_is_versioned_in_same_transaction():
    before = _state_row()
    after = _state_row(
        revision=2,
        snapshot={
            "workbookSheet": "账单",
            "excelMapping": {"name": "姓名", "hours": "工时", "amount": "金额"},
        },
    )
    connection = FakeConnection([FakeResult(row=before), FakeResult(row=after), FakeResult()])

    updated, changed = state_postgres.transition_labor_run_state(
        "labor-1",
        lambda snapshot: {
            **snapshot,
            "workbookSheet": "账单",
            "excelMapping": {"name": "姓名", "hours": "工时", "amount": "金额"},
        },
        actor_user_id="user-1",
        action="workbook_mapping_changed",
        connect=lambda: connection,
    )

    assert changed is True
    assert updated["stateRevision"] == 2
    assert "update public.labor_runs" in connection.queries[1][0].lower()
    assert "insert into public.labor_workbook_mappings" in connection.queries[2][0].lower()
    assert connection.committed is True


def test_p1_business_review_redecision_is_versioned_with_actor_and_fingerprint():
    fingerprint = "b" * 64
    before = _state_row(
        snapshot={
            "businessReviewStatus": "approved",
            "businessReviewReason": "初次核对无误",
            "businessReviewedBy": "reviewer-old",
            "resultInputFingerprint": fingerprint,
        }
    )
    after = _state_row(
        revision=2,
        snapshot={
            "businessReviewStatus": "approved",
            "businessReviewReason": "补充核对银行汇总后仍无误",
            "businessReviewedBy": "reviewer-new",
            "resultInputFingerprint": fingerprint,
        },
    )
    connection = FakeConnection([FakeResult(row=before), FakeResult(row=after), FakeResult()])

    updated, changed = state_postgres.transition_labor_run_state(
        "labor-1",
        lambda snapshot: {
            **snapshot,
            "businessReviewStatus": "approved",
            "businessReviewReason": "补充核对银行汇总后仍无误",
            "businessReviewedBy": "reviewer-new",
            "resultInputFingerprint": fingerprint,
        },
        actor_user_id="reviewer-new",
        connect=lambda: connection,
    )

    assert changed is True
    assert updated["stateRevision"] == 2
    review_sql, review_params = connection.queries[2]
    assert "insert into public.labor_business_reviews" in review_sql.lower()
    assert review_params == (
        "labor-1",
        "user-1",
        "reviewer-new",
        "approved",
        "补充核对银行汇总后仍无误",
        fingerprint,
        2,
    )
    assert connection.committed is True


def test_p1_run_helpers_treat_postgres_as_authority(tmp_path, monkeypatch):
    state = {}

    def create_state(payload, **_kwargs):
        stored = {**payload, "stateRevision": 1}
        state[stored["id"]] = stored
        return dict(stored)

    def load_state(run_id, **_kwargs):
        if run_id not in state:
            raise state_postgres.LaborStateNotFound(run_id)
        return dict(state[run_id])

    def list_states(**_kwargs):
        return [dict(value) for value in state.values()]

    def transition_state(run_id, transition, **_kwargs):
        before = dict(state[run_id])
        proposed = transition(before)
        if proposed is None:
            return before, False
        after = {**proposed, "stateRevision": int(before["stateRevision"]) + 1}
        state[run_id] = after
        return dict(after), True

    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(labor_runs, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(labor_runs, "create_labor_run_state", create_state)
    monkeypatch.setattr(labor_runs, "load_labor_run_state", load_state)
    monkeypatch.setattr(labor_runs, "list_labor_run_states", list_states)
    monkeypatch.setattr(labor_runs, "transition_labor_run_state", transition_state)
    monkeypatch.setattr(labor_runs, "labor_persistent_storage_enabled", lambda: False)

    created = labor_runs.create_labor_run(
        {
            "supplierName": "State Supplier",
            "ownerUserId": "owner-1",
            "periodStart": "2026-07-01",
            "periodEnd": "2026-07-07",
        }
    )
    run_dir = tmp_path / "runs" / created["id"]
    stale = {**created, "ownerUserId": "stale-local-owner", "status": "stale"}
    labor_runs._write_labor_metadata_file(run_dir / "metadata.json", stale)

    loaded = labor_runs.load_labor_metadata(run_dir)
    updated = labor_runs.update_labor_metadata(created["id"], {"status": "已上传文件"})
    listed = labor_runs.list_labor_metadata()

    assert loaded["ownerUserId"] == "owner-1"
    assert loaded["status"] == "已创建"
    assert updated["stateRevision"] == 2
    assert listed[0]["status"] == "已上传文件"
    assert labor_runs._read_labor_metadata_file(run_dir / "metadata.json")["stateRevision"] == 2


def test_p1_audit_helpers_use_postgres_instead_of_local_jsonl(tmp_path, monkeypatch):
    captured = []
    expected = [{"action": "files_uploaded", "ownerUserId": "owner-1"}]
    monkeypatch.setattr(labor_audit, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(
        labor_audit,
        "append_labor_audit_event_state",
        lambda **kwargs: captured.append(kwargs),
    )
    monkeypatch.setattr(
        labor_audit,
        "read_labor_audit_events_state",
        lambda **_kwargs: expected,
    )
    audit_path = tmp_path / "audit.jsonl"

    event = labor_audit.append_labor_audit_event(
        audit_path,
        action="files_uploaded",
        run_id="labor-1",
        owner_user_id="owner-1",
        actor_user_id="owner-1",
    )
    rows = labor_audit.read_labor_audit_events(audit_path)

    assert event["action"] == "files_uploaded"
    assert captured[0]["run_id"] == "labor-1"
    assert rows == expected
    assert not audit_path.exists()


def test_p1_postgres_cache_never_syncs_a_legacy_object_snapshot(tmp_path, monkeypatch):
    sync_calls = []
    run_dir = tmp_path / "runs" / "labor-1"
    monkeypatch.setattr(labor_runs, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(labor_runs, "labor_persistent_storage_enabled", lambda: True)
    monkeypatch.setattr(
        labor_runs,
        "sync_labor_run_to_persistent",
        lambda run_id, path: sync_calls.append((run_id, path)),
    )

    cached = labor_runs._cache_authoritative_labor_metadata(
        run_dir,
        {
            "id": "labor-1",
            "ownerUserId": "owner-1",
            "status": "已创建",
            "stateRevision": 1,
            "files": {},
        },
    )

    assert cached["ownerUserId"] == "owner-1"
    assert (run_dir / "metadata.json").is_file()
    assert sync_calls == []


def test_p1_pending_file_manifest_locks_run_before_inserting():
    file_row = {
        "id": "file-1",
        "run_id": "labor-1",
        "owner_user_id": "user-1",
        "file_kind": "pdf_invoice",
        "object_key": "labor-runs/uat/owners/user-1/runs/labor-1/inputs/file-1/invoice.pdf",
        "original_filename": "invoice.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1024,
        "sha256": "a" * 64,
        "upload_state": "pending",
    }
    connection = FakeConnection(
        [FakeResult(row=_state_row()), FakeResult(), FakeResult(row=file_row), FakeResult()]
    )

    created = state_postgres.create_pending_labor_file_state(
        run_id="labor-1",
        owner_user_id="user-1",
        actor_user_id="user-1",
        file_id="file-1",
        file_kind="pdf_invoice",
        object_key=file_row["object_key"],
        original_filename="invoice.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        sha256="a" * 64,
        connect=lambda: connection,
    )

    assert "from public.labor_runs" in connection.queries[0][0].lower()
    assert "for update" in connection.queries[0][0].lower()
    assert "upload_state='rejected'" in connection.queries[1][0].lower()
    assert "insert into public.labor_run_files" in connection.queries[2][0].lower()
    assert created["uploadState"] == "pending"
    assert connection.committed is True


def test_p1_pending_file_batch_enforces_cumulative_limit_under_run_lock():
    connection = FakeConnection(
        [
            FakeResult(row=_state_row()),
            FakeResult(),
            FakeResult(rows=[{"file_kind": "pdf_invoice", "active_count": 30}]),
        ]
    )

    with pytest.raises(state_postgres.LaborStateConflict, match="PDF 文件数量已达到上限"):
        state_postgres.create_pending_labor_file_states(
            run_id="labor-1",
            owner_user_id="user-1",
            actor_user_id="user-1",
            files=[
                {
                    "file_id": "file-31",
                    "file_kind": "pdf_invoice",
                    "object_key": "labor-runs/uat/owners/user-1/runs/labor-1/inputs/file-31/invoice.pdf",
                    "original_filename": "invoice.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 1024,
                    "sha256": "a" * 64,
                }
            ],
            max_files_by_kind={"pdf_invoice": 30, "workbook": 3},
            connect=lambda: connection,
        )

    assert connection.rolled_back is True
    assert not any("insert into public.labor_run_files" in sql.lower() for sql, _ in connection.queries)


def test_p1_finalize_file_manifest_verifies_expected_size_and_hash():
    file_row = {
        "id": "file-1",
        "run_id": "labor-1",
        "owner_user_id": "user-1",
        "file_kind": "pdf_invoice",
        "object_key": "labor-runs/uat/owners/user-1/runs/labor-1/inputs/file-1/invoice.pdf",
        "original_filename": "invoice.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1024,
        "sha256": "a" * 64,
        "upload_state": "pending",
    }
    ready_row = {**file_row, "upload_state": "ready"}
    ready_run = _state_row(
        revision=2,
        snapshot={
            "status": "已上传文件",
            "files": {
                "pdfInvoices": [
                    {
                        "id": "file-1",
                        "objectKey": file_row["object_key"],
                        "uploadState": "ready",
                    }
                ],
                "workbooks": [],
            },
        },
    )
    connection = FakeConnection(
        [
            FakeResult(row=_state_row()),
            FakeResult(row=file_row),
            FakeResult(row=ready_row),
            FakeResult(rows=[ready_row]),
            FakeResult(row=ready_run),
            FakeResult(),
        ]
    )

    ready = state_postgres.finalize_labor_file_state(
        run_id="labor-1",
        owner_user_id="user-1",
        actor_user_id="user-1",
        file_id="file-1",
        observed_size_bytes=1024,
        reported_sha256="a" * 64,
        connect=lambda: connection,
    )

    assert "from public.labor_runs" in connection.queries[0][0].lower()
    assert "from public.labor_run_files" in connection.queries[1][0].lower()
    assert "for update" in connection.queries[1][0].lower()
    assert "update public.labor_runs" in connection.queries[4][0].lower()
    run_update_payload = connection.queries[4][1][1]
    assert '"objectKey":"labor-runs/uat/owners/user-1/' in run_update_payload
    assert ready["uploadState"] == "ready"

    mismatch_connection = FakeConnection([FakeResult(row=_state_row()), FakeResult(row=file_row)])
    with pytest.raises(state_postgres.LaborStateConflict):
        state_postgres.finalize_labor_file_state(
            run_id="labor-1",
            owner_user_id="user-1",
            actor_user_id="user-1",
            file_id="file-1",
            observed_size_bytes=2048,
            reported_sha256="a" * 64,
            connect=lambda: mismatch_connection,
        )
    assert mismatch_connection.rolled_back is True


def test_p1_result_outputs_do_not_rewrite_or_reclassify_authoritative_input_manifest():
    input_files = {
        "pdfInvoices": [
            {
                "id": "pdf-1",
                "fileKind": "pdf_invoice",
                "objectKey": "labor-runs/uat/pdf-1/invoice.pdf",
                "originalFilename": "invoice.pdf",
                "sizeBytes": 100,
                "sha256": "a" * 64,
            }
        ],
        "workbooks": [
            {
                "id": "xlsx-1",
                "fileKind": "workbook",
                "objectKey": "labor-runs/uat/xlsx-1/bill.xlsx",
                "originalFilename": "bill.xlsx",
                "sizeBytes": 200,
                "sha256": "b" * 64,
            }
        ],
    }
    connection = FakeConnection([])

    state_postgres._sync_derived_state(
        connection,
        {"files": input_files},
        {
            "files": {
                **input_files,
                "diffReport": {
                    "filename": "result.xlsx",
                    "sizeBytes": 300,
                    "sha256": "c" * 64,
                },
            }
        },
        "labor-1",
        "user-1",
        "worker-user-1",
        2,
    )

    assert connection.queries == []
